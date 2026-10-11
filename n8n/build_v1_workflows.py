"""Génère les 4 workflows n8n de la V1 (risk-triage, risk-verify, shift-report, pharmacy-alerts) dans n8n/workflows/.
Sans secret : identifiants de credentials et configuration en jetons __X__ remplacés à l'import (n8n/setup_n8n.py).

    python n8n/build_v1_workflows.py
"""
import json
import sys
import uuid
from pathlib import Path

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "workflows"
NS = uuid.UUID("6f1d2c1e-0000-4000-8000-00000000c0de")

CRED = {
    "anthropic": {"httpHeaderAuth": {"id": "__CRED_ANTHROPIC__", "name": "Hospital Copilot — Anthropic (x-api-key)"}},
    "platform": {"httpHeaderAuth": {"id": "__CRED_PLATFORM__", "name": "Hospital Copilot — Plateforme (jeton de service)"}},
    "secret": {"httpHeaderAuth": {"id": "__CRED_WEBHOOK__", "name": "Hospital Copilot — Webhook (X-Hospital-Secret)"}},
    "telegram": {"telegramApi": {"id": "__CRED_TELEGRAM__", "name": "Hospital Copilot — Telegram"}},
}

CONFIG_JS = r"""// Configuration : l'événement de la plateforme est prioritaire ; sinon valeurs posées à l'import (n8n/setup_n8n.py).
const CFG = { platform_url: '__PLATFORM_URL__', telegram_chat_id: '__TELEGRAM_CHAT_ID__', llm_model: '__LLM_MODEL__' };
const DEF = { platform_url: 'http://localhost:8000', telegram_chat_id: '', llm_model: 'claude-sonnet-5-5' };
const cfg = (k, v) => v || (String(CFG[k]).startsWith('__') ? DEF[k] : CFG[k]);
// n8n (Node) résout « localhost » en IPv6 (::1) alors que la plateforme écoute en IPv4 : on force 127.0.0.1.
const platformUrl = (v) => cfg('platform_url', v).replace(/\/$/, '').replace('//localhost', '//127.0.0.1');
const esc = (s) => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
"""

PARSE_JS = r"""// Extrait l'objet JSON de la réponse Anthropic (content[].text) ; lève une erreur si absent ou invalide.
function parseClaude(res) {
  if (!res || res.error) throw new Error(typeof (res || {}).error === 'string' ? res.error : ((res || {}).error || {}).message || 'appel Anthropic en échec');
  const text = (res.content || []).filter((b) => b.type === 'text').map((b) => b.text).join('');
  if (!text) throw new Error('réponse vide');
  const m = text.match(/\{[\s\S]*\}/);
  return JSON.parse(m ? m[0] : text);
}
const esc = (s) => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
"""


class WF:
    def __init__(self, name):
        self.name, self.nodes, self.conn, self.col, self.row = name, [], {}, 0, 0

    def _id(self, name):
        return str(uuid.uuid5(NS, f"{self.name}/{name}"))

    def add(self, name, type_, version, params, pos, creds=None, **extra):
        n = {"parameters": params, "id": self._id(name), "name": name, "type": type_, "typeVersion": version, "position": list(pos)}
        if creds:
            n["credentials"] = creds
        n.update(extra)
        self.nodes.append(n)
        return name

    def link(self, a, b, out=0):
        outs = self.conn.setdefault(a, {"main": []})["main"]
        while len(outs) <= out:
            outs.append([])
        outs[out].append({"node": b, "type": "main", "index": 0})

    # ── fabriques ────────────────────────────────────────────────────────────
    def webhook(self, name, path, pos):
        return self.add(name, "n8n-nodes-base.webhook", 2, {"httpMethod": "POST", "path": path, "authentication": "headerAuth", "responseMode": "onReceived", "options": {}}, pos, CRED["secret"], webhookId=self._id("wh-" + path))

    def cron(self, name, expr, pos):
        return self.add(name, "n8n-nodes-base.scheduleTrigger", 1.2, {"rule": {"interval": [{"field": "cronExpression", "expression": expr}]}}, pos)

    def code(self, name, js, pos):
        return self.add(name, "n8n-nodes-base.code", 2, {"jsCode": js.strip() + "\n"}, pos)

    def claude(self, name, pos, timeout=60000):
        return self.add(name, "n8n-nodes-base.httpRequest", 4.2, {
            "method": "POST", "url": "https://api.anthropic.com/v1/messages",
            "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
            "sendHeaders": True, "headerParameters": {"parameters": [{"name": "anthropic-version", "value": "2023-06-01"}, {"name": "content-type", "value": "application/json"}]},
            "sendBody": True, "specifyBody": "json", "jsonBody": "={{ JSON.stringify($json.request) }}",
            "options": {"timeout": timeout},
        }, pos, CRED["anthropic"], onError="continueRegularOutput", retryOnFail=True, maxTries=2, waitBetweenTries=2000)

    def platform(self, name, method, url, pos, body=None, soft=False):
        params = {"method": method, "url": url, "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth", "options": {"timeout": 15000}}
        if body:
            params.update({"sendBody": True, "specifyBody": "json", "jsonBody": body})
        extra = {"retryOnFail": True, "maxTries": 3, "waitBetweenTries": 1500}
        if soft:
            extra["onError"] = "continueRegularOutput"
        return self.add(name, "n8n-nodes-base.httpRequest", 4.2, params, pos, CRED["platform"], **extra)

    def log(self, name, pos, ctx, step, reasoning, output, status="ok", risk=True, agent=None):
        """Étape clé → POST /api/agents/log (panneau Agents de la plateforme). `ctx` = expression JS de l'item de contexte."""
        fields = [("agent", agent or self.name), ("room", f"={{{{ {ctx}.room || '' }}}}"), ("input", step), ("reasoning", reasoning), ("output", output), ("status", status),
                  ("duration_ms", f"={{{{ Date.now() - ({ctx}.started_at || Date.now()) }}}}")]
        if risk:
            fields.append(("risk_id", f"={{{{ {ctx}.risk_id }}}}"))
        params = {"method": "POST", "url": f"={{{{ {ctx}.platform_url }}}}/api/agents/log", "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
                  "sendBody": True, "bodyParameters": {"parameters": [{"name": k, "value": v} for k, v in fields]}, "options": {"timeout": 8000}}
        return self.add(name, "n8n-nodes-base.httpRequest", 4.2, params, pos, CRED["platform"], onError="continueRegularOutput")

    def telegram(self, name, pos, ctx):
        return self.add(name, "n8n-nodes-base.telegram", 1.2, {"chatId": f"={{{{ {ctx}.chat_id }}}}", "text": f"={{{{ {ctx}.telegram_text }}}}",
                                                                   "additionalFields": {"appendAttribution": False, "parse_mode": "HTML"}}, pos, CRED["telegram"], onError="continueRegularOutput",
                        webhookId=self._id("tg-" + name))

    def if_true(self, name, expr, pos):
        return self.add(name, "n8n-nodes-base.if", 2.2, {
            "conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
                           "conditions": [{"id": self._id("cond-" + name), "leftValue": expr, "rightValue": "", "operator": {"type": "boolean", "operation": "true", "singleValue": True}}],
                           "combinator": "and"},
            "looseTypeValidation": True, "options": {}}, pos)

    def dump(self):
        data = {"name": self.name, "nodes": self.nodes, "connections": self.conn, "settings": {"executionOrder": "v1"}, "active": False}
        (OUT / f"{self.name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(self.name, len(self.nodes), "nœuds")


X, Y = 240, 300


def P(col, row=0):
    return (col * X, Y + row * 200)


# ═════════════════════════════════════════════════════════════════════════════
# 1. risk-triage
# ═════════════════════════════════════════════════════════════════════════════
w = WF("risk-triage")
w.webhook("Webhook risk-created", "risk-created", P(0))
w.code("Construire le prompt", CONFIG_JS + r"""
const body = $input.first().json.body || {};
const risk = body.risk || {};
const patient = body.patient || {};
if (!risk.id) throw new Error('événement risk-created sans risque');

const context = {
  risque: { type: risk.type, libelle: risk.type_label, titre: risk.title, severite: risk.severity, chambre: risk.room, detecte_le: risk.detected_at, explication_deterministe: risk.explanation },
  patient: { nom: patient.full_name, age: patient.age, sexe: patient.sex, allergies: patient.allergies || 'aucune connue', risque_de_chute: patient.fall_risk, antecedents: patient.history, groupe_sanguin: patient.blood_group },
  traitements_en_cours: body.treatments && body.treatments.length ? body.treatments : (body.treatments_text || 'aucun'),
  dernieres_constantes: body.vitals || {},
  news2: body.news2,
  etat_vision: body.vision || {},
  environnement: body.env || {},
  personnel_en_service: body.staff_on_duty || [],
  infirmier_dans_la_chambre: !!body.nurse_present,
};

const system = [
  "Tu es l'assistant d'aide à la décision d'une clinique (Hospital Copilot). Tu aides l'infirmier(ère) à réagir à un risque détecté par des règles déterministes.",
  "Règles : n'invente JAMAIS de valeur ; cite les valeurs mesurées fournies (constantes, NEWS2, posture) ; respecte strictement les allergies et les traitements en cours ; ne prescris rien : tu suggères, un soignant valide.",
  "La sévérité est déjà fixée par la plateforme : ne la modifie pas.",
  "Réponds en français, UNIQUEMENT par un objet JSON valide, sans texte autour et sans balise Markdown.",
].join('\n');
const user = `Contexte (JSON) :\n${JSON.stringify(context, null, 1)}\n\nRédige :\n- "explanation" : 2 à 4 phrases expliquant le risque pour CE patient en citant les valeurs ;\n- "steps" : un plan d'action de 3 à 6 étapes concrètes, ordonnées, chacune de moins de 200 caractères.\n\nFormat exact : {"explanation": "...", "steps": [{"text": "..."}, {"text": "..."}]}`;

const model = cfg('llm_model', body.llm_model);
return [{ json: {
  started_at: Date.now(),
  risk_id: risk.id, room: risk.room, severity: risk.severity, title: risk.title, risk_type: risk.type,
  base_explanation: risk.explanation || '',
  patient_name: patient.full_name || 'Patient',
  platform_url: platformUrl(body.platform_url),
  chat_id: cfg('telegram_chat_id', body.telegram_chat_id),
  wait_seconds: Number(body.wait_seconds) || ({ critical: 120, high: 600 }[risk.severity] || 1800),
  model,
  request: { model, max_tokens: 8000, system, messages: [{ role: 'user', content: user }] },
} }];
""", P(1))
C1 = "$('Construire le prompt').first().json"
w.log("Journal : événement reçu", P(2, -1), C1, "=webhook risk-created : {{ $json.title }} [{{ $json.severity }}] — {{ $json.patient_name }}",
      "=Prompt construit (patient, allergies, traitements, constantes, vision). Appel de l'API Anthropic ({{ $json.model }}).", "appel Claude en cours")
w.claude("Claude : explication + plan", P(2))
V1 = "$('Valider le JSON').first().json"
w.code("Valider le JSON", PARSE_JS + r"""
const ctx = $('Construire le prompt').first().json;
const res = $input.first().json;
const SEV = { low: 'FAIBLE', medium: 'MODÉRÉ', high: 'ÉLEVÉ', critical: 'CRITIQUE' };
const FALLBACK = {
  fall: ["Se rendre immédiatement au chevet du patient et évaluer la conscience.", "Ne pas relever le patient avant l'évaluation des douleurs et d'un traumatisme (tête, hanche).", "Mesurer les constantes (FC, PA, SpO2, glycémie capillaire).", "Prévenir le médecin de garde et tracer la chute dans le dossier."],
  default: ["Se rendre au chevet du patient et évaluer son état clinique.", "Contrôler les constantes et les comparer aux dernières valeurs enregistrées.", "Vérifier les traitements en cours et les allergies avant toute administration.", "Prévenir le médecin de garde si l'état ne s'améliore pas."],
};

let explanation = '', steps = [], error = null;
try {
  const out = parseClaude(res);
  explanation = String(out.explanation || '').trim();
  steps = (Array.isArray(out.steps) ? out.steps : []).map((s) => String((s && s.text) || (typeof s === 'string' ? s : '')).trim()).filter(Boolean).map((s) => s.slice(0, 300));
  if (!explanation) throw new Error('explication manquante');
  if (steps.length < 3 || steps.length > 6) throw new Error(`plan de ${steps.length} étape(s) : 3 à 6 attendues`);
} catch (e) { error = e.message; }

const fallback = error !== null;
if (fallback) { explanation = ctx.base_explanation; steps = FALLBACK[ctx.risk_type] || FALLBACK.default; }

// URL de reprise du nœud Wait (suffixe risk-ack), stockée par la plateforme pour « Je prends en charge »
const [base, qs] = String($execution.resumeUrl).split('?');
const resume_url = `${base}/risk-ack${qs ? '?' + qs : ''}`;

const telegram_text = [
  `🚨 <b>[${SEV[ctx.severity] || ctx.severity}] ${esc(ctx.title)}</b>`,
  `Chambre <b>${esc(ctx.room)}</b> — ${esc(ctx.patient_name)}`,
  '', esc(explanation), '',
  '<b>Plan d\'action' + (fallback ? ' (secours)' : ' (IA, à valider)') + '</b>',
  ...steps.map((s, i) => `${i + 1}. ${esc(s)}`),
  '', `Centre de commande → « Je prends en charge » : ${ctx.platform_url}/`,
  `Sans prise en charge sous ${Math.round(ctx.wait_seconds / 60 * 10) / 10} min : escalade au médecin de garde.`,
].join('\n');

return [{ json: {
  started_at: ctx.started_at, risk_id: ctx.risk_id, room: ctx.room, severity: ctx.severity, title: ctx.title, patient_name: ctx.patient_name,
  platform_url: ctx.platform_url, chat_id: ctx.chat_id, wait_seconds: ctx.wait_seconds,
  fallback, error, steps_count: steps.length, model_used: (res && res.model) || ctx.model, usage: (res && res.usage) || null, anthropic_id: (res && res.id) || null,
  plan: { explanation, steps, fallback, source: 'n8n:risk-triage', llm_provider: `anthropic ${(res && res.model) || ctx.model} (n8n)`, resume_url },
  telegram_text,
} }];
""", P(3))
w.platform("Plateforme : enregistrer le plan", "POST", "={{ $json.platform_url }}/api/risks/{{ $json.risk_id }}/plan", P(4), body="={{ JSON.stringify($json.plan) }}")
w.telegram("Telegram : infirmier", P(5), V1)
w.log("Journal : plan et alerte envoyés", P(6, -1), V1,
      f"=réponse Anthropic {{{{ {V1}.anthropic_id || '(aucune)' }}}} — {{{{ {V1}.model_used }}}}",
      f"={{{{ {V1}.fallback ? 'RÉPONSE DE SECOURS (LLM indisponible) : ' + {V1}.error : 'JSON validé : explication + plan de ' + {V1}.steps_count + ' étapes, allergies et traitements respectés.' }}}} Plan enregistré sur la plateforme, Telegram infirmier {{{{ $json.ok ? 'envoyé' : 'non envoyé (' + ($json.error || 'Telegram non configuré') + ')' }}}}.",
      f"=attente d'acquittement « Je prends en charge » ({{{{ {V1}.wait_seconds }}}} s) avant escalade", status=f"={{{{ {V1}.fallback ? 'error' : 'ok' }}}}")
w.add("Attendre l'acquittement (risk-ack)", "n8n-nodes-base.wait", 1.1, {
    "resume": "webhook", "incomingAuthentication": "headerAuth", "httpMethod": "POST", "responseMode": "onReceived",
    "limitWaitTime": True, "limitType": "afterTimeInterval", "resumeAmount": f"={{{{ $('Plateforme : enregistrer le plan').first().json.status === 'open' ? {V1}.wait_seconds : 1 }}}}", "resumeUnit": "seconds",
    "options": {"webhookSuffix": "risk-ack"}}, P(6), CRED["secret"], webhookId=w._id("wait-risk-ack"))
w.code("Acquitté ?", r"""
// Reprise par le webhook risk-ack (body.acknowledged) ou expiration du délai (données d'entrée inchangées)
const ctx = $('Valider le JSON').first().json;
const b = ($input.first().json || {}).body || {};
const acked = b.acknowledged === true && Number(b.risk_id) === Number(ctx.risk_id);
const SEV = { low: 'FAIBLE', medium: 'MODÉRÉ', high: 'ÉLEVÉ', critical: 'CRITIQUE' };
const esc = (s) => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const minutes = Math.round(ctx.wait_seconds / 60 * 10) / 10;
return [{ json: {
  acked, by: b.by || null,
  started_at: ctx.started_at, risk_id: ctx.risk_id, room: ctx.room, platform_url: ctx.platform_url, chat_id: ctx.chat_id, wait_seconds: ctx.wait_seconds,
  escalation: { reason: `Aucune prise en charge en ${minutes} min (délai ${ctx.severity}) — escalade par n8n.`, source: 'n8n:risk-triage' },
  telegram_text: `⬆️ <b>ESCALADE — médecin de garde</b>\n<b>[${SEV[ctx.severity] || ctx.severity}] ${esc(ctx.title)}</b>\nChambre <b>${esc(ctx.room)}</b> — ${esc(ctx.patient_name)}\nAucun acquittement infirmier en ${minutes} min.\n${ctx.platform_url}/`,
} }];
""", P(7))
A1 = "$('Acquitté ?').first().json"
w.if_true("Pris en charge ?", "={{ $json.acked }}", P(8))
w.log("Journal : acquitté", P(9, -1), A1, "=reprise par le webhook risk-ack", "=« Je prends en charge » reçu de la plateforme : l'attente est levée, pas d'escalade.",
      f"=pris en charge par {{{{ {A1}.by || 'un soignant' }}}}")
w.platform("Plateforme : escalader", "POST", "={{ $json.platform_url }}/api/risks/{{ $json.risk_id }}/escalate", P(9, 1), body="={{ JSON.stringify($json.escalation) }}")
w.if_true("Escaladé ?", "={{ $json.escalated }}", P(10, 1))
w.telegram("Telegram : médecin de garde", P(11, 0), A1)
w.log("Journal : escalade", P(12, 0), A1, f"=délai d'acquittement dépassé ({{{{ {A1}.wait_seconds }}}} s)",
      "=Aucun acquittement reçu sur le webhook risk-ack : risque escaladé sur la plateforme, Telegram au médecin de garde {{ $json.ok ? 'envoyé' : 'non envoyé' }}.",
      "risque escaladé au médecin de garde", status="error")
w.log("Journal : escalade annulée", P(11, 2), A1, f"=délai d'acquittement dépassé ({{{{ {A1}.wait_seconds }}}} s)",
      "=La plateforme indique que le risque est déjà pris en charge (personnel dans la chambre) ou résolu : pas d'escalade.", "=statut : {{ $json.status }}")
for a, b in [("Webhook risk-created", "Construire le prompt"), ("Construire le prompt", "Journal : événement reçu"), ("Construire le prompt", "Claude : explication + plan"),
             ("Claude : explication + plan", "Valider le JSON"), ("Valider le JSON", "Plateforme : enregistrer le plan"), ("Plateforme : enregistrer le plan", "Telegram : infirmier"),
             ("Telegram : infirmier", "Journal : plan et alerte envoyés"), ("Telegram : infirmier", "Attendre l'acquittement (risk-ack)"), ("Attendre l'acquittement (risk-ack)", "Acquitté ?"),
             ("Acquitté ?", "Pris en charge ?"), ("Plateforme : escalader", "Escaladé ?"), ("Telegram : médecin de garde", "Journal : escalade")]:
    w.link(a, b)
w.link("Pris en charge ?", "Journal : acquitté", 0)
w.link("Pris en charge ?", "Plateforme : escalader", 1)
w.link("Escaladé ?", "Telegram : médecin de garde", 0)
w.link("Escaladé ?", "Journal : escalade annulée", 1)
w.dump()

# ═════════════════════════════════════════════════════════════════════════════
# 2. risk-verify
# ═════════════════════════════════════════════════════════════════════════════
w = WF("risk-verify")
w.webhook("Webhook staff-left", "staff-left", P(0))
w.code("Contexte", CONFIG_JS + r"""
const body = $input.first().json.body || {};
const ids = (body.risk_ids || []).map(Number).filter(Boolean);
if (!body.room || !ids.length) throw new Error('événement staff-left sans chambre ou sans risque');
return [{ json: {
  started_at: Date.now(),
  room: String(body.room), risk_ids: ids, risk_id: ids[0], risks: body.risks || [],
  patient: body.patient || {}, duration_s: body.duration_s ?? null,
  recheck_seconds: Number(body.recheck_seconds) || 120,
  platform_url: platformUrl(body.platform_url),
  chat_id: cfg('telegram_chat_id', body.telegram_chat_id),
  model: cfg('llm_model', body.llm_model),
} }];
""", P(1))
C2 = "$('Contexte').first().json"
w.log("Journal : sortie du personnel", P(2, -1), C2, "=webhook staff-left : le personnel a quitté la chambre {{ $json.room }} (risques {{ $json.risk_ids.join(', ') }})",
      "=Attente de {{ $json.recheck_seconds }} s (2 min simulées) avant de relire l'état réel de la chambre.", "re-vérification planifiée")
w.add("Attendre 2 min", "n8n-nodes-base.wait", 1.1, {"amount": "={{ $json.recheck_seconds }}", "unit": "seconds"}, P(2), webhookId=w._id("wait-recheck"))
w.platform("Plateforme : état de la chambre", "GET", f"={{{{ {C2}.platform_url }}}}/api/rooms/{{{{ {C2}.room }}}}/state", P(3))
w.code("Construire le prompt", r"""
const ctx = $('Contexte').first().json;
const state = $input.first().json || {};
// Seuls les risques encore ouverts et délégués à ce workflow sont re-vérifiés
const risks = (state.open_risks || []).filter((r) => ctx.risk_ids.includes(Number(r.id)));
if (!risks.length) return [];

const context = {
  chambre: ctx.room,
  patient: { nom: ctx.patient.full_name, age: ctx.patient.age, allergies: ctx.patient.allergies, antecedents: ctx.patient.history },
  duree_de_la_visite_s: ctx.duration_s,
  etat_actuel: { posture: state.posture, activite: state.activity, zone: state.zone, expression: state.expression, personnes: state.persons, temperature_cutanee_c: state.skinTempC },
  constantes_actuelles: state.vitals || {},
  environnement: state.env || {},
  risques_a_verifier: risks.map((r) => ({ risk_id: r.id, type: r.type, libelle: r.type_label, titre: r.title, severite: r.severity, explication: r.explanation, controle_deterministe: r.auto_check })),
};
const system = [
  "Tu es l'assistant de vérification d'une clinique (Hospital Copilot). Le personnel vient de quitter la chambre : tu dois dire, pour chaque risque, s'il est résolu d'après l'ÉTAT ACTUEL mesuré.",
  "Règles : n'invente aucune valeur ; cite les valeurs actuelles (posture, activité, constantes) dans ta justification ; en cas de doute, le risque n'est PAS résolu.",
  "Réponds en français, UNIQUEMENT par un objet JSON valide, sans texte autour et sans balise Markdown.",
].join('\n');
const user = `Contexte (JSON) :\n${JSON.stringify(context, null, 1)}\n\nFormat exact : {"verdicts": [{"risk_id": 0, "resolved": true, "justification": "1 à 2 phrases courtes (300 caractères au plus) citant les valeurs"}]}`;
return [{ json: { risks, state_summary: context.etat_actuel, vitals: context.constantes_actuelles, request: { model: ctx.model, max_tokens: 8000, system, messages: [{ role: 'user', content: user }] } } }];
""", P(4))
w.claude("Claude : risque résolu ?", P(5))
w.code("Valider le verdict", PARSE_JS + r"""
const ctx = $('Contexte').first().json;
const prep = $('Construire le prompt').first().json;
const res = $input.first().json;
let verdicts = [], error = null;
try {
  const out = parseClaude(res);
  verdicts = Array.isArray(out.verdicts) ? out.verdicts : [];
  if (!verdicts.length) throw new Error('aucun verdict');
} catch (e) { error = e.message; }

return prep.risks.map((r) => {
  const v = verdicts.find((x) => Number(x.risk_id) === Number(r.id));
  const check = r.auto_check || { ok: false, detail: 'contrôle indisponible' };
  const fallback = !v || typeof v.resolved !== 'boolean';
  // Garde-fou : jamais « résolu » si le contrôle déterministe de la plateforme échoue ; sans réponse du LLM, seul ce contrôle décide.
  const resolved = fallback ? check.ok === true : (v.resolved === true && check.ok === true);
  let justification = fallback ? `Réponse de secours (LLM indisponible${error ? ' : ' + error : ''}) — contrôle déterministe : ${check.detail}.` : String(v.justification || '').trim();
  if (!fallback && v.resolved === true && !check.ok) justification += ` (Contrôle déterministe en échec : ${check.detail} — risque maintenu.)`;
  const head = resolved ? `✅ <b>Résolu et vérifié</b> — ${esc(r.title)}` : `⚠️ <b>Risque persistant après visite</b> — ${esc(r.title)}`;
  return { json: {
    started_at: ctx.started_at, risk_id: r.id, room: ctx.room, platform_url: ctx.platform_url, chat_id: ctx.chat_id,
    resolved, fallback, justification, title: r.title, model_used: (res && res.model) || ctx.model, anthropic_id: (res && res.id) || null,
    body: { verified: true, justification, reason: justification, source: 'n8n:risk-verify' },
    telegram_text: `${head}\nChambre <b>${esc(ctx.room)}</b> — ${esc(ctx.patient.full_name || 'Patient')}\n${esc(justification)}\n${resolved ? '' : 'Médecin de garde sollicité.\n'}${ctx.platform_url}/`,
  } };
});
""", P(6))
VV = "$('Valider le verdict').item.json"
w.if_true("Résolu ?", "={{ $json.resolved }}", P(7))
w.platform("Plateforme : résoudre", "POST", "={{ $json.platform_url }}/api/risks/{{ $json.risk_id }}/resolve", P(8, -1), body="={{ JSON.stringify($json.body) }}")
w.telegram("Telegram : confirmation", P(9, -1), VV)
w.log("Journal : résolu", P(10, -1), VV, f"=état réel relu après attente — réponse Anthropic {{{{ {VV}.anthropic_id || '(aucune)' }}}} ({{{{ {VV}.model_used }}}})",
      f"={{{{ {VV}.justification }}}}", f"=risque #{{{{ {VV}.risk_id }}}} résolu et vérifié", status=f"={{{{ {VV}.fallback ? 'error' : 'ok' }}}}", agent="risk-verify")
w.platform("Plateforme : risque persistant", "POST", "={{ $json.platform_url }}/api/risks/{{ $json.risk_id }}/persistent", P(8, 1), body="={{ JSON.stringify($json.body) }}")
w.telegram("Telegram : alerte", P(9, 1), VV)
w.log("Journal : persistant", P(10, 1), VV, f"=état réel relu après attente — réponse Anthropic {{{{ {VV}.anthropic_id || '(aucune)' }}}} ({{{{ {VV}.model_used }}}})",
      f"={{{{ {VV}.justification }}}}", f"=risque #{{{{ {VV}.risk_id }}}} persistant : escalade au médecin de garde", status="error")
for a, b in [("Webhook staff-left", "Contexte"), ("Contexte", "Journal : sortie du personnel"), ("Contexte", "Attendre 2 min"), ("Attendre 2 min", "Plateforme : état de la chambre"),
             ("Plateforme : état de la chambre", "Construire le prompt"), ("Construire le prompt", "Claude : risque résolu ?"), ("Claude : risque résolu ?", "Valider le verdict"),
             ("Valider le verdict", "Résolu ?"), ("Plateforme : résoudre", "Telegram : confirmation"), ("Telegram : confirmation", "Journal : résolu"),
             ("Plateforme : risque persistant", "Telegram : alerte"), ("Telegram : alerte", "Journal : persistant")]:
    w.link(a, b)
w.link("Résolu ?", "Plateforme : résoudre", 0)
w.link("Résolu ?", "Plateforme : risque persistant", 1)
w.dump()

# ═════════════════════════════════════════════════════════════════════════════
# 3. shift-report
# ═════════════════════════════════════════════════════════════════════════════
w = WF("shift-report")
w.cron("Cron 07:45 et 19:45", "45 7,19 * * *", P(0, -1))
w.webhook("Webhook shift-report", "shift-report", P(0, 0))
w.code("Contexte", CONFIG_JS + r"""
const body = $input.first().json.body || {};   // vide quand le déclencheur est le Cron
const hours = Math.max(1, Math.min(Number(body.hours) || 12, 48));
const end = new Date();
const start = new Date(end.getTime() - hours * 3600 * 1000);
return [{ json: {
  started_at: Date.now(), room: '',
  trigger: body.event ? `bouton de la plateforme (${body.triggered_by || '?'})` : 'Cron 07:45 / 19:45',
  hours, since: start.toISOString(), until: end.toISOString(),
  platform_url: platformUrl(body.platform_url),
  chat_id: cfg('telegram_chat_id', body.telegram_chat_id),
  model: cfg('llm_model', body.llm_model),
} }];
""", P(1))
C3 = "$('Contexte').first().json"
w.platform("Plateforme : événements, risques, humeurs", "GET", "={{ $json.platform_url }}/api/events?since={{ encodeURIComponent($json.since) }}", P(2))
w.code("Construire le prompt", r"""
const ctx = $('Contexte').first().json;
const d = $input.first().json || {};
const rooms = Object.keys(d.rooms || {}).sort();
const by = (arr, room) => (arr || []).filter((x) => String(x.room) === room);
const data = rooms.map((room) => ({
  chambre: room,
  etat_actuel: d.rooms[room],
  risques: by(d.risks, room).map((r) => ({ titre: r.title, type: r.type, severite: r.severity, statut: r.status, detecte_le: r.detected_at, resolu_le: r.resolved_at, escalade_le: r.escalated_at, cloture_par: r.resolved_by,
    plan: r.plan ? r.plan.steps.map((s) => ({ etape: s.text, faite: !!s.done, par: s.done_by })) : [] })),
  evenements: by(d.state_events, room).slice(-40).map((e) => `${e.ts.slice(11, 19)} ${e.posture}/${e.activity}${e.persons > 1 ? ' (personnel présent)' : ''}`),
  humeurs: by(d.moods, room).slice(-12).map((m) => `${m.ts.slice(11, 16)} ${m.mood}${m.note ? ' — ' + m.note : ''}`),
  visites_du_personnel: by(d.visits, room).length,
}));
const system = [
  "Tu rédiges le rapport de garde (relève infirmière) d'une clinique à partir de données mesurées. Aide à la décision : le rapport sera relu et validé par l'infirmier(ère) responsable.",
  "Règles : n'invente rien ; cite les valeurs et les heures fournies ; si une information manque, écris « non renseigné ».",
  "Réponds en français, UNIQUEMENT par un objet JSON valide, sans texte autour et sans balise Markdown.",
].join('\n');
const user = `Période : du ${ctx.since} au ${ctx.until} (UTC).\nDonnées par chambre (JSON) :\n${JSON.stringify(data, null, 1)}\n\nFormat exact :\n{"summary": "synthèse de la garde en 2-3 phrases", "rooms": [{"room": "101", "patient_state": "état actuel + constantes citées", "events": ["..."], "risks": ["titre [sévérité, statut]"], "actions": ["actions réalisées"], "mood": "humeur observée"}], "handover": ["points d'attention pour la relève"]}`;
return [{ json: { data, counts: { risks: (d.risks || []).length, events: (d.state_events || []).length, moods: (d.moods || []).length },
  request: { model: ctx.model, max_tokens: 12000, system, messages: [{ role: 'user', content: user }] } } }];
""", P(3))
w.claude("Claude : rapport de garde", P(4), timeout=120000)
w.code("Valider et mettre en forme", PARSE_JS + r"""
const ctx = $('Contexte').first().json;
const prep = $('Construire le prompt').first().json;
const res = $input.first().json;
const fmt = (iso) => String(iso).slice(0, 16).replace('T', ' ') + ' UTC';
const list = (a) => (Array.isArray(a) && a.length ? a.map(String).join(' ; ') : 'aucun');
let out = null, error = null;
try {
  out = parseClaude(res);
  if (!Array.isArray(out.rooms) || !out.rooms.length) throw new Error('rapport sans chambre');
} catch (e) { error = e.message; out = null; }
const fallback = out === null;
const lines = [`# Rapport de garde — ${fmt(ctx.since)} → ${fmt(ctx.until)}`, ''];
if (fallback) {
  lines.push('_Réponse de secours (LLM indisponible) — synthèse automatique des données, à compléter par l\'infirmier(ère) responsable._', '');
  for (const r of prep.data) {
    const e = r.etat_actuel || {};
    lines.push(`## Chambre ${r.chambre}`, `- **État actuel** : posture ${e.posture}, activité ${e.activity}, expression ${e.expression}.`,
      `- **Risques** (${r.risques.length}) : ${list(r.risques.map((x) => `${x.titre} [${x.severite}, ${x.statut}]`))}.`, `- **Humeur observée** : ${r.humeurs.slice(-1)[0] || 'non évaluée'}.`, '');
  }
} else {
  lines.push(`_Rédigé par n8n (workflow shift-report, ${(res && res.model) || ctx.model}) — aide à la décision, à valider par l'infirmier(ère) responsable._`, '', String(out.summary || '').trim(), '');
  for (const r of out.rooms) {
    lines.push(`## Chambre ${r.room}`, `- **État actuel** : ${r.patient_state || 'non renseigné'}`, `- **Événements** : ${list(r.events)}`, `- **Risques** : ${list(r.risks)}`,
      `- **Actions réalisées** : ${list(r.actions)}`, `- **Humeur observée** : ${r.mood || 'non évaluée'}`, '');
  }
  lines.push('## Points d\'attention pour la relève', ...((out.handover || []).length ? out.handover.map((h) => `- ${h}`) : ['- Aucun point particulier.']));
}
return [{ json: {
  started_at: ctx.started_at, room: '', platform_url: ctx.platform_url, chat_id: ctx.chat_id, fallback, error, counts: prep.counts,
  model_used: (res && res.model) || ctx.model, anthropic_id: (res && res.id) || null,
  report: { content: lines.join('\n'), hours: ctx.hours, shift_start: ctx.since, shift_end: ctx.until, source: 'n8n:shift-report', fallback },
} }];
""", P(5))
V3 = "$('Valider et mettre en forme').first().json"
w.platform("Plateforme : enregistrer le rapport", "POST", "={{ $json.platform_url }}/api/shift-reports", P(6), body="={{ JSON.stringify($json.report) }}")
w.code("Préparer le message", r"""
const v = $('Valider et mettre en forme').first().json;
const rep = $input.first().json;
const link = `${v.platform_url}${rep.print_url || '/print/shift/' + rep.id}`;
return [{ json: { ...v, report: undefined, report_id: rep.id, link,
  telegram_text: `📝 <b>Rapport de garde #${rep.id}</b> prêt (brouillon${v.fallback ? ' — réponse de secours' : ''}).\n${v.counts.risks} risque(s), ${v.counts.moods} observation(s) d'humeur sur la période.\nÀ valider puis imprimer : ${link}` } }];
""", P(7))
M3 = "$('Préparer le message').first().json"
w.telegram("Telegram : lien d'impression", P(8), M3)
w.log("Journal : rapport déposé", P(9), M3, f"=déclencheur : {{{{ {C3}.trigger }}}} — {{{{ {M3}.counts.risks }}}} risque(s), {{{{ {M3}.counts.events }}}} événement(s), {{{{ {M3}.counts.moods }}}} humeur(s)",
      f"={{{{ {M3}.fallback ? 'RÉPONSE DE SECOURS (LLM indisponible) : ' + {M3}.error : 'Rapport structuré par chambre rédigé par ' + {M3}.model_used + ' (réponse ' + {M3}.anthropic_id + '), JSON validé.' }}}}",
      f"=rapport de garde #{{{{ {M3}.report_id }}}} déposé (brouillon), lien d'impression envoyé sur Telegram", status=f"={{{{ {M3}.fallback ? 'error' : 'ok' }}}}", risk=False)
for a, b in [("Cron 07:45 et 19:45", "Contexte"), ("Webhook shift-report", "Contexte"), ("Contexte", "Plateforme : événements, risques, humeurs"),
             ("Plateforme : événements, risques, humeurs", "Construire le prompt"), ("Construire le prompt", "Claude : rapport de garde"), ("Claude : rapport de garde", "Valider et mettre en forme"),
             ("Valider et mettre en forme", "Plateforme : enregistrer le rapport"), ("Plateforme : enregistrer le rapport", "Préparer le message"),
             ("Préparer le message", "Telegram : lien d'impression"), ("Telegram : lien d'impression", "Journal : rapport déposé")]:
    w.link(a, b)
w.dump()

# ═════════════════════════════════════════════════════════════════════════════
# 4. pharmacy-alerts
# ═════════════════════════════════════════════════════════════════════════════
w = WF("pharmacy-alerts")
w.cron("Cron quotidien 08:00", "0 8 * * *", P(0, -1))
w.webhook("Webhook pharmacy-alerts", "pharmacy-alerts", P(0, 0))
w.code("Contexte", CONFIG_JS + r"""
const body = $input.first().json.body || {};   // vide quand le déclencheur est le Cron
return [{ json: {
  started_at: Date.now(), room: '',
  trigger: body.event ? `bouton de la plateforme (${body.triggered_by || '?'})` : 'Cron quotidien 08:00',
  platform_url: platformUrl(body.platform_url),
  chat_id: cfg('telegram_chat_id', body.telegram_chat_id),
} }];
""", P(1))
w.platform("Plateforme : alertes pharmacie", "GET", "={{ $json.platform_url }}/api/pharmacy/alerts?days=30", P(2))
w.code("Composer le message", r"""
const ctx = $('Contexte').first().json;
const d = $input.first().json || {};
const esc = (s) => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const low = d.low_stock || [], exp = d.expiring || [];
const day = (s) => String(s || '').slice(0, 10).split('-').reverse().join('/');
const lines = ['💊 <b>Alertes pharmacie</b>'];
if (low.length) lines.push('', `<b>Stock sous le seuil (${low.length})</b>`, ...low.slice(0, 15).map((m) => `• ${esc(m.dci)} (${esc(m.brand)}) : ${m.stock} / seuil ${m.threshold}`));
if (exp.length) lines.push('', `<b>Péremption sous 30 jours (${exp.length})</b>`, ...exp.slice(0, 15).map((m) => `• ${esc(m.dci)} (${esc(m.brand)}) : ${day(m.expiry)}`));
lines.push('', `${ctx.platform_url}/`);
return [{ json: { ...ctx, has_alerts: low.length + exp.length > 0, low: low.length, expiring: exp.length, telegram_text: lines.join('\n') } }];
""", P(3))
M4 = "$('Composer le message').first().json"
w.if_true("Des alertes ?", "={{ $json.has_alerts }}", P(4))
w.telegram("Telegram : pharmacien", P(5, -1), M4)
w.log("Journal : alertes envoyées", P(6, -1), M4, f"=déclencheur : {{{{ {M4}.trigger }}}} — GET /api/pharmacy/alerts?days=30",
      f"={{{{ {M4}.low }}}} médicament(s) sous le seuil de stock, {{{{ {M4}.expiring }}}} avec péremption sous 30 jours.",
      "=Telegram au pharmacien {{ $json.ok ? 'envoyé' : 'non envoyé (' + ($json.error || 'Telegram non configuré') + ')' }}", risk=False)
w.log("Journal : aucune alerte", P(5, 1), M4, f"=déclencheur : {{{{ {M4}.trigger }}}} — GET /api/pharmacy/alerts?days=30", "Aucun stock sous le seuil, aucune péremption sous 30 jours.", "pas de message envoyé", risk=False)
for a, b in [("Cron quotidien 08:00", "Contexte"), ("Webhook pharmacy-alerts", "Contexte"), ("Contexte", "Plateforme : alertes pharmacie"), ("Plateforme : alertes pharmacie", "Composer le message"),
             ("Composer le message", "Des alertes ?"), ("Telegram : pharmacien", "Journal : alertes envoyées")]:
    w.link(a, b)
w.link("Des alertes ?", "Telegram : pharmacien", 0)
w.link("Des alertes ?", "Journal : aucune alerte", 1)
w.dump()
