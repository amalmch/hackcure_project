"""
Génère un workflow n8n par agent V2 à partir de `dashboard/app/agents/specs.py` (source unique des prompts).

    python n8n/build_agent_workflows.py          # écrit n8n/workflows/<workflow>.json

Forme commune (les 4 workflows V1 — risk-triage, risk-verify, shift-report, pharmacy-alerts — gardent leur forme propre) :

    Webhook <workflow> (X-Hospital-Secret)
      → Code « Construire le prompt » (consigne de l'agent + contexte envoyé par la plateforme)
      → HTTP Anthropic (credential x-api-key)
      → Code « Valider le JSON » (clés obligatoires ; sinon réponse de secours signalée)
      → POST {PLATFORM_URL}/api/agents/result (jeton de service) : le gestionnaire Python de l'agent applique le résultat
      → Telegram si la plateforme renvoie un message

Aucun secret : les credentials sont désignés par des jetons `__CRED_*__` remplacés à l'import (n8n/setup_n8n.py).
"""

from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "n8n" / "workflows"
NS = uuid.UUID("6f1d2c1e-0000-4000-8000-00000000c0de")
CRED = {
    "anthropic": {"httpHeaderAuth": {"id": "__CRED_ANTHROPIC__", "name": "Hospital Copilot — Anthropic (x-api-key)"}},
    "platform": {"httpHeaderAuth": {"id": "__CRED_PLATFORM__", "name": "Hospital Copilot — Plateforme (jeton de service)"}},
    "secret": {"httpHeaderAuth": {"id": "__CRED_WEBHOOK__", "name": "Hospital Copilot — Webhook (X-Hospital-Secret)"}},
    "telegram": {"telegramApi": {"id": "__CRED_TELEGRAM__", "name": "Hospital Copilot — Telegram"}},
}


def load_specs():
    spec = importlib.util.spec_from_file_location("hc_specs", ROOT / "dashboard" / "app" / "agents" / "specs.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hc_specs"] = mod
    spec.loader.exec_module(mod)
    return mod


PROMPT_JS = r"""// Configuration : l'événement de la plateforme est prioritaire ; sinon valeurs posées à l'import (n8n/setup_n8n.py).
const CFG = { platform_url: '__PLATFORM_URL__', telegram_chat_id: '__TELEGRAM_CHAT_ID__', llm_model: '__LLM_MODEL__' };
const DEF = { platform_url: 'http://localhost:8000', telegram_chat_id: '', llm_model: 'claude-sonnet-5-5' };
const cfg = (k, v) => v || (String(CFG[k]).startsWith('__') ? DEF[k] : CFG[k]);
// n8n (Node) résout « localhost » en IPv6 (::1) alors que la plateforme écoute en IPv4 : on force 127.0.0.1.
const platformUrl = (v) => cfg('platform_url', v).replace(/\/$/, '').replace('//localhost', '//127.0.0.1');

// Consigne de l'agent %(agent)s — source : dashboard/app/agents/specs.py
const SYSTEM = %(system)s;
const FORMAT = %(format)s;

const body = $input.first().json.body || {};
if (!body.ref) throw new Error('événement %(name)s sans référence');
const context = body.context || {};
const model = cfg('llm_model', body.llm_model);
const user = `Contexte (JSON) :\n${JSON.stringify(context, null, 1)}\n\nFormat exact attendu :\n${FORMAT}`;
return [{ json: {
  started_at: Date.now(), workflow: '%(name)s', ref: String(body.ref), room: body.room || '', risk_id: body.risk_id ?? null,
  platform_url: platformUrl(body.platform_url), chat_id: cfg('telegram_chat_id', body.telegram_chat_id), model, context,
  request: { model, max_tokens: %(max_tokens)d, system: SYSTEM, messages: [{ role: 'user', content: user }] },
} }];
"""

VALIDATE_JS = r"""// Extrait l'objet JSON de la réponse Anthropic et vérifie les clés obligatoires.
const REQUIRED = %(required)s;
const ctx = $('Construire le prompt').first().json;
const res = $input.first().json;
let result = null, error = null;
try {
  if (!res || res.error) throw new Error(typeof (res || {}).error === 'string' ? res.error : ((res || {}).error || {}).message || 'appel Anthropic en échec');
  const text = (res.content || []).filter((b) => b.type === 'text').map((b) => b.text).join('');
  if (!text) throw new Error('réponse vide');
  if (res.stop_reason === 'max_tokens') throw new Error('réponse tronquée (max_tokens)');
  const m = text.match(/\{[\s\S]*\}/);
  result = JSON.parse(m ? m[0] : text);
  const missing = REQUIRED.filter((k) => result[k] === undefined || result[k] === null || result[k] === '' || (Array.isArray(result[k]) && !result[k].length));
  if (missing.length) throw new Error('clé(s) manquante(s) : ' + missing.join(', '));
} catch (e) { error = e.message; result = null; }
const fallback = result === null;
return [{ json: {
  platform_url: ctx.platform_url, chat_id: ctx.chat_id, fallback, error,
  // en secours, le contexte repart vers la plateforme : elle construit la réponse déterministe de l'agent
  payload: { workflow: ctx.workflow, ref: ctx.ref, result, context: fallback ? ctx.context : null, fallback, error, model: (res && res.model) || ctx.model, anthropic_id: (res && res.id) || null,
             room: ctx.room || null, risk_id: ctx.risk_id, duration_ms: Date.now() - ctx.started_at },
} }];
"""


def build(name: str, s: dict, rules: str) -> dict:
    nid = lambda n: str(uuid.uuid5(NS, f"{name}/{n}"))  # noqa: E731
    X, Y = 240, 300
    http_auth = {"authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth"}
    js = lambda v: json.dumps(v, ensure_ascii=False)  # noqa: E731
    nodes = [
        {"parameters": {"httpMethod": "POST", "path": s["webhook"], "authentication": "headerAuth", "responseMode": "onReceived", "options": {}}, "id": nid("webhook"), "name": f"Webhook {s['webhook']}",
         "type": "n8n-nodes-base.webhook", "typeVersion": 2, "position": [0, Y], "credentials": CRED["secret"], "webhookId": nid("wh-" + s["webhook"])},
        {"parameters": {"jsCode": PROMPT_JS % {"agent": s["agent"], "name": name, "system": js(rules + "\n" + s["system"]), "format": js(s["format"]), "max_tokens": int(s.get("max_tokens", 1800))}},
         "id": nid("prompt"), "name": "Construire le prompt", "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [X, Y]},
        {"parameters": {"method": "POST", "url": "={{ $json.platform_url }}/api/agents/log", **http_auth, "sendBody": True, "bodyParameters": {"parameters": [
            {"name": "agent", "value": name}, {"name": "room", "value": "={{ $json.room }}"}, {"name": "input", "value": f"=webhook {s['webhook']} — {s['title']} ({{{{ $json.ref }}}})"},
            {"name": "reasoning", "value": f"=Contexte reçu de {s['agent']} (détection et sévérité déterministes). Appel de l'API Anthropic ({{{{ $json.model }}}})."}, {"name": "output", "value": "appel Claude en cours"}]},
            "options": {"timeout": 8000}}, "id": nid("log"), "name": "Journal : événement reçu", "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2, "position": [2 * X, Y - 200],
         "credentials": CRED["platform"], "onError": "continueRegularOutput"},
        {"parameters": {"method": "POST", "url": "https://api.anthropic.com/v1/messages", **http_auth, "sendHeaders": True,
                        "headerParameters": {"parameters": [{"name": "anthropic-version", "value": "2023-06-01"}, {"name": "content-type", "value": "application/json"}]},
                        "sendBody": True, "specifyBody": "json", "jsonBody": "={{ JSON.stringify($json.request) }}", "options": {"timeout": 90000}},
         "id": nid("claude"), "name": f"Claude : {s['title'][:48]}", "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2, "position": [2 * X, Y], "credentials": CRED["anthropic"],
         "onError": "continueRegularOutput", "retryOnFail": True, "maxTries": 2, "waitBetweenTries": 2000},
        {"parameters": {"jsCode": VALIDATE_JS % {"required": js(s.get("required", []))}}, "id": nid("validate"), "name": "Valider le JSON", "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [3 * X, Y]},
        {"parameters": {"method": "POST", "url": "={{ $json.platform_url }}/api/agents/result", **http_auth, "sendBody": True, "specifyBody": "json", "jsonBody": "={{ JSON.stringify($json.payload) }}", "options": {"timeout": 20000}},
         "id": nid("result"), "name": f"Plateforme : résultat pour {s['agent']}", "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2, "position": [4 * X, Y], "credentials": CRED["platform"],
         "retryOnFail": True, "maxTries": 3, "waitBetweenTries": 1500},
        {"parameters": {"conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
                                       "conditions": [{"id": nid("cond"), "leftValue": "={{ !!$json.telegram_text }}", "rightValue": "", "operator": {"type": "boolean", "operation": "true", "singleValue": True}}], "combinator": "and"},
                        "looseTypeValidation": True, "options": {}}, "id": nid("if"), "name": "Message à envoyer ?", "type": "n8n-nodes-base.if", "typeVersion": 2.2, "position": [5 * X, Y]},
        {"parameters": {"chatId": "={{ $('Valider le JSON').first().json.chat_id }}", "text": "={{ $json.telegram_text }}", "additionalFields": {"appendAttribution": False, "parse_mode": "HTML"}},
         "id": nid("telegram"), "name": "Telegram", "type": "n8n-nodes-base.telegram", "typeVersion": 1.2, "position": [6 * X, Y - 100], "credentials": CRED["telegram"], "onError": "continueRegularOutput", "webhookId": nid("tg")},
    ]
    names = [n["name"] for n in nodes]
    link = lambda b: [{"node": b, "type": "main", "index": 0}]  # noqa: E731
    conn = {
        names[0]: {"main": [link(names[1])]},
        names[1]: {"main": [link(names[2]) + link(names[3])]},
        names[3]: {"main": [link(names[4])]},
        names[4]: {"main": [link(names[5])]},
        names[5]: {"main": [link(names[6])]},
        names[6]: {"main": [link(names[7]), []]},
    }
    return {"name": name, "nodes": nodes, "connections": conn, "settings": {"executionOrder": "v1"}, "active": False}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    specs = load_specs()
    OUT.mkdir(parents=True, exist_ok=True)
    for name, s in specs.SPECS.items():
        wf = build(name, s, specs.RULES)
        (OUT / f"{name}.json").write_text(json.dumps(wf, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"  {name:22} ← {s['agent']}  ({len(wf['nodes'])} nœuds, webhook /{s['webhook']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
