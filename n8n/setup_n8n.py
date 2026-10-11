"""
Installe l'orchestration n8n de Hospital Copilot via l'API publique de n8n (bibliothèque standard uniquement) :

1. crée ou met à jour les 4 credentials (Anthropic, Telegram, jeton de service de la plateforme, secret des webhooks) ;
2. importe les 4 workflows de n8n/workflows/ (création, ou mise à jour si le nom existe déjà) ;
3. les ACTIVE.

Les secrets sont lus dans .env et ne vont que dans les credentials n8n : les JSON du dépôt n'en contiennent aucun.

    python n8n/setup_n8n.py [--env .env] [--platform-url http://localhost:8000] [--no-activate] [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# tous les workflows du dossier : les 4 de la V1 + un par agent V2 (générés par n8n/build_agent_workflows.py)
WORKFLOWS = sorted(p.stem for p in (ROOT / "n8n" / "workflows").glob("*.json"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def read_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


class N8n:
    def __init__(self, base: str, key: str) -> None:
        self.base, self.key = base.rstrip("/") + "/api/v1", key

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        req = urllib.request.Request(self.base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"X-N8N-API-KEY": self.key, "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read().decode()
                return r.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            raw = e.read().decode(errors="replace")
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, {"message": raw[:300]}

    def all(self, path: str) -> list[dict]:
        out, cursor = [], None
        while True:
            code, d = self.call("GET", f"{path}?limit=100" + (f"&cursor={cursor}" if cursor else ""))
            if code != 200:
                raise RuntimeError(f"GET {path} → HTTP {code} {d.get('message', '')}")
            out += d.get("data", [])
            cursor = d.get("nextCursor")
            if not cursor:
                return out


def credentials_wanted(env: dict[str, str]) -> dict[str, dict]:
    """jeton du JSON → (nom, type, données). Les valeurs viennent de .env."""
    return {
        "__CRED_ANTHROPIC__": {"name": "Hospital Copilot — Anthropic (x-api-key)", "type": "httpHeaderAuth", "data": {"name": "x-api-key", "value": env.get("ANTHROPIC_API_KEY", "")}, "requires": "ANTHROPIC_API_KEY"},
        "__CRED_PLATFORM__": {"name": "Hospital Copilot — Plateforme (jeton de service)", "type": "httpHeaderAuth", "data": {"name": "Authorization", "value": "Bearer " + env.get("PLATFORM_SERVICE_TOKEN", "")}, "requires": "PLATFORM_SERVICE_TOKEN"},
        "__CRED_WEBHOOK__": {"name": "Hospital Copilot — Webhook (X-Hospital-Secret)", "type": "httpHeaderAuth", "data": {"name": "X-Hospital-Secret", "value": env.get("N8N_WEBHOOK_SECRET", "")}, "requires": "N8N_WEBHOOK_SECRET"},
        "__CRED_TELEGRAM__": {"name": "Hospital Copilot — Telegram", "type": "telegramApi", "data": {"accessToken": env.get("TELEGRAM_BOT_TOKEN", "")}, "requires": "TELEGRAM_BOT_TOKEN"},
    }


def ensure_credentials(api: N8n, env: dict[str, str]) -> dict[str, str]:
    try:
        existing = {c["name"]: c["id"] for c in api.all("/credentials")}
    except RuntimeError:
        existing = {}  # anciennes versions de n8n : pas de liste → création systématique
    ids: dict[str, str] = {}
    for token, c in credentials_wanted(env).items():
        if not env.get(c["requires"]):
            print(f"  ! {c['requires']} absent de .env : credential « {c['name']} » créé vide (à compléter dans n8n)")
            if c["type"] == "telegramApi":
                c["data"]["accessToken"] = "non-configure"
        body = {"name": c["name"], "type": c["type"], "data": c["data"]}
        cid = existing.get(c["name"])
        if cid:
            code, d = api.call("PATCH", f"/credentials/{cid}", body)
            if code >= 300:  # pas de PATCH sur cette version : suppression puis création
                api.call("DELETE", f"/credentials/{cid}")
                cid = None
        if not cid:
            code, d = api.call("POST", "/credentials", body)
            if code >= 300:
                raise RuntimeError(f"création du credential « {c['name']} » : HTTP {code} {d.get('message', '')}")
            cid = d["id"]
            print(f"  + credential créé : {c['name']}")
        else:
            print(f"  = credential mis à jour : {c['name']}")
        ids[token] = cid
    return ids


def load_workflow(name: str, tokens: dict[str, str]) -> dict:
    raw = (ROOT / "n8n" / "workflows" / f"{name}.json").read_text(encoding="utf-8")
    for token, value in tokens.items():
        raw = raw.replace(token, json.dumps(value)[1:-1])
    wf = json.loads(raw)
    return {k: wf[k] for k in ("name", "nodes", "connections", "settings")}  # seuls champs acceptés par l'API


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env", default=str(ROOT / ".env"))
    ap.add_argument("--platform-url", help="URL de la plateforme vue depuis n8n (défaut : PLATFORM_URL de .env)")
    ap.add_argument("--no-activate", action="store_true")
    ap.add_argument("--check", action="store_true", help="vérifie seulement l'API et l'état des workflows")
    args = ap.parse_args()

    env = read_env(Path(args.env))
    base, key = env.get("N8N_BASE_URL", "http://localhost:5678"), env.get("N8N_API_KEY", "")
    if not key:
        print("N8N_API_KEY absent de .env. Dans n8n : Settings → n8n API → Create an API key, puis ajouter N8N_API_KEY=… dans .env.\n"
              "Sans clé d'API : `npx n8n import:workflow --separate --input=n8n/workflows`, puis créer les credentials à la main (voir n8n/README.md).")
        return 2
    api = N8n(base, key)
    try:
        current = {w["name"]: w for w in api.all("/workflows")}
    except Exception as exc:
        print(f"L'API n8n ne répond pas sur {api.base} ({exc}). Lancer n8n (`npx n8n`) et vérifier N8N_API_KEY.")
        return 2

    if args.check:
        for name in WORKFLOWS:
            w = current.get(name)
            print(f"  {name:22} {'ACTIF' if w and w.get('active') else 'inactif' if w else 'ABSENT'}" + (f"  ({w['id']})" if w else ""))
        return 0 if all(current.get(n, {}).get("active") for n in WORKFLOWS) else 1

    print(f"n8n : {api.base}")
    tokens = ensure_credentials(api, env)
    tokens.update({"__PLATFORM_URL__": (args.platform_url or env.get("PLATFORM_URL", "http://localhost:8000")).rstrip("/"),
                   "__TELEGRAM_CHAT_ID__": env.get("TELEGRAM_CHAT_ID", ""), "__LLM_MODEL__": env.get("LLM_MODEL", "claude-sonnet-5-5")})
    failed = False
    for name in WORKFLOWS:
        wf = load_workflow(name, tokens)
        old = current.get(name)
        if old:
            if old.get("active"):
                api.call("POST", f"/workflows/{old['id']}/deactivate")
            code, d = api.call("PUT", f"/workflows/{old['id']}", wf)
        else:
            code, d = api.call("POST", "/workflows", wf)
        if code >= 300:
            print(f"  ✗ {name} : HTTP {code} {d.get('message', '')}")
            failed = True
            continue
        wid, state = d["id"], "importé"
        if not args.no_activate:
            code, a = api.call("POST", f"/workflows/{wid}/activate")
            state = "ACTIF" if code < 300 and a.get("active", True) else f"NON ACTIVÉ (HTTP {code} {a.get('message', '')})"
            failed = failed or code >= 300
        print(f"  ✓ {name:22} {'mis à jour' if old else 'créé'} — {state}  →  {base}/workflow/{wid}")
    print("Terminé." if not failed else "Terminé avec des erreurs.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
