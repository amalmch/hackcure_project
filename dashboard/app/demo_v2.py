"""
Pilote automatique de la démonstration V2 (`full_demo_v2`).

Le scénario YAML enchaîne des actions de simulateur (constantes, postures…) et des étapes `noop` portant un champ
`hook` : ces étapes sont les gestes que des HUMAINS feraient pendant la démo (sortie d'un patient, départ de
l'ambulance, réponses au questionnaire, bilan clinique du médecin, validation du bilan biologique, ordonnance de
traitement, « Je prends en charge »…). Le pilote les joue à leur place **en passant par l'API de la plateforme**
avec le jeton de service : aucun raccourci, ce sont les mêmes endpoints, permissions et agents que pour un vrai
utilisateur. Chaque geste simulé est journalisé (« Démo V2 — geste simulé »).

`run(hook, params, call)` : `call(method, url, json)` est une coroutine qui appelle l'API (client ASGI interne en
production, client de test dans les tests d'intégration).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger("hackcure.demo_v2")
Call = Callable[[str, str, Optional[dict[str, Any]]], Awaitable[tuple[int, Any]]]
journal: list[dict[str, Any]] = []  # gestes simulés du dernier passage (lu par le test d'intégration et la doc)


async def _retry(fn: Callable[[], Awaitable[Any]], tries: int = 8, delay: float = 0.5) -> Any:
    """Attend qu'une précondition soit remplie (ex. le risque existe), sans bloquer indéfiniment."""
    for _ in range(tries):
        v = await fn()
        if v:
            return v
        await asyncio.sleep(delay)
    return None


async def _open_risk(call: Call, room: str, types: list[str]) -> Optional[dict[str, Any]]:
    _, rows = await call("GET", f"/api/risks?room={room}&open_only=1", None)
    for r in rows or []:
        if r["type"] in types and r["status"] in ("open", "escalated"):
            return r
    return None


async def discharge(call: Call, p: dict[str, Any]) -> str:
    code, _ = await call("POST", f"/api/records/{p['patient']}/discharge", None)
    return "sortie enregistrée, chambre libre" if code == 200 else "patient déjà sorti"


async def ambulance(call: Call, p: dict[str, Any]) -> str:
    body = {"patient_id": p["patient"], "reason": p.get("reason", "Chute à domicile, douleur de hanche"), "emergency_type": p.get("emergency", "trauma"), "severity": int(p.get("severity", 2)),
            "vitals": p.get("vitals", {"FC": "98", "PA": "136/82", "SpO2": "97"}), "mode": "sim", "route": p.get("route", "proche"), "time_scale": p.get("time_scale")}
    code, m = await call("POST", "/api/ambulances/missions", body)
    return f"mission #{m['id']} : chambre {m['reserved_room']} réservée" if code == 201 else f"départ refusé ({m.get('detail') if isinstance(m, dict) else code})"


async def questionnaire(call: Call, p: dict[str, Any]) -> str:
    async def url() -> Optional[str]:
        _, d = await call("GET", f"/api/psych/{p['patient']}", None)
        q = (d or {}).get("questionnaire")
        # tant que la patiente n'est pas installée (pas de séjour en cours), on attend le questionnaire du nouveau séjour
        return q["url"] if q and q["status"] == "pending" and (d or {}).get("room") else None

    link = await _retry(url, tries=int(p.get("tries", 12)))
    if not link:
        return "questionnaire non disponible (patient pas encore installé)"
    answers = p.get("answers") or {"phq9": [1, 2, 1, 2, 1, 1, 1, 0, 0], "gad7": [2, 2, 1, 2, 1, 1, 1], "sleep": [2, 3, 2, 2, 1, 2]}
    code, _ = await call("POST", f"/api/psych/questionnaire/{link.rsplit('/', 1)[1]}", answers)
    return "questionnaire rempli sur la tablette" if code == 200 else f"questionnaire refusé ({code})"


async def _pathway(call: Call, room: str) -> Optional[dict[str, Any]]:
    _, rows = await call("GET", f"/api/fever?room={room}&open_only=1", None)
    return rows[0] if rows else None


async def fever_exam(call: Call, p: dict[str, Any]) -> str:
    path = await _retry(lambda: _pathway(call, p["room"]))
    if not path:
        return "pas de parcours fièvre ouvert"
    for key, note in (("foyer", "crépitants à la base droite"), ("conscience", "conscient, orienté"), ("hydratation", "muqueuses sèches"), ("sepsis", None), ("allergies", None)):
        await call("POST", f"/api/fever/{path['id']}/checklist", {"key": key, "done": True, **({"note": note} if note else {})})
    code, d = await call("POST", f"/api/fever/{path['id']}/exam-done", None)
    return f"bilan clinique conclu (parcours #{path['id']})" if code == 200 else f"bilan clinique refusé ({code})"


async def fever_labs(call: Call, p: dict[str, Any]) -> str:
    path = await _retry(lambda: _pathway(call, p["room"]))
    if not path:
        return "pas de parcours fièvre ouvert"
    code, d = await call("POST", f"/api/fever/{path['id']}/labs/validate", {})
    return f"bilan biologique validé ; {d['comfort_note'][:80]}" if code == 200 else f"validation refusée ({code})"


async def treatment_order(call: Call, p: dict[str, Any]) -> str:
    _, meds = await call("GET", "/api/pharmacy/medications", None)
    med = next((m for m in meds or [] if m["brand"] == p.get("brand", "Doliprane")), None)
    if not med:
        return "médicament introuvable"
    code, o = await call("POST", "/api/treatment-orders", {"patient_id": p["patient"], "indication": p.get("indication", "Fièvre"), "lines": [
        {"medication_id": med["id"], "dose": p.get("dose", "1 g"), "route": p.get("route", "PO"), "times": ["08:00", "14:00", "20:00"], "duration_days": 2}]})
    if code != 201:
        return f"ordonnance refusée ({code})"
    code, s = await call("POST", f"/api/treatment-orders/{o['id']}/sign", {"first_dose_in_s": float(p.get("first_dose_in_s", 20))})
    return f"ordonnance #{o['id']} signée : {s['doses']['total']} prises planifiées" if code == 200 else f"signature refusée ({code})"


async def give_dose(call: Call, p: dict[str, Any]) -> str:
    async def due() -> Optional[dict[str, Any]]:
        _, plan = await call("GET", f"/api/care-plan?room={p['room']}", None)
        rows = (plan or {}).get("due", []) + (plan or {}).get("late", [])
        return rows[0] if rows else None

    d = await _retry(due)
    if not d:
        return "aucune prise due"
    code, _ = await call("POST", f"/api/care-plan/doses/{d['id']}/give", {"note": "administré pendant la démonstration"})
    return f"prise administrée : {d['label']}" if code == 200 else f"administration refusée ({code})"


async def ack(call: Call, p: dict[str, Any]) -> str:
    types = list(p["types"]) if isinstance(p.get("types"), list) else [p.get("types")]
    risk = await _retry(lambda: _open_risk(call, p["room"], types), tries=int(p.get("tries", 8)))
    if not risk:
        return f"aucun risque ouvert parmi {types}"
    code, d = await call("POST", f"/api/risks/{risk['id']}/ack", None)
    res = (d or {}).get("resolution") or {}
    return f"risque #{risk['id']} ({risk['type']}) pris en charge" + (f" — {res.get('role_label')} en route" if res else "") if code == 200 else f"prise en charge refusée ({code})"


HOOKS: dict[str, Callable[[Call, dict[str, Any]], Awaitable[str]]] = {
    "demo_discharge": discharge, "demo_ambulance": ambulance, "demo_questionnaire": questionnaire, "demo_fever_exam": fever_exam, "demo_fever_labs": fever_labs,
    "demo_treatment_order": treatment_order, "demo_give_dose": give_dose, "demo_ack": ack,
}
LABELS = {"demo_discharge": "réception : sortie d'un patient", "demo_ambulance": "régulation : départ de l'ambulance", "demo_questionnaire": "patient : questionnaire sur tablette",
          "demo_fever_exam": "médecin de garde : bilan clinique", "demo_fever_labs": "médecin de garde : validation du bilan biologique", "demo_treatment_order": "médecin : ordonnance de traitement",
          "demo_give_dose": "infirmier : administration", "demo_ack": "soignant : « Je prends en charge »"}


async def run(hook: str, params: dict[str, Any], call: Call) -> str:
    fn = HOOKS.get(hook)
    if fn is None:
        return f"geste inconnu : {hook}"
    try:
        out = await fn(call, params)
    except Exception as exc:  # un geste raté ne doit jamais arrêter la démo
        logger.exception("démo V2 : %s", hook)
        out = f"erreur : {exc.__class__.__name__}"
    journal.append({"hook": hook, "params": {k: v for k, v in params.items() if k != "hook"}, "result": out})
    logger.info("DÉMO V2 — %s → %s", LABELS.get(hook, hook), out)
    return out


# ─── production : le pilote appelle l'API par un client ASGI interne (jeton de service) ──────────────────────
async def _asgi_call(method: str, url: str, json: Optional[dict[str, Any]]) -> tuple[int, Any]:
    import httpx

    from .config import settings
    from .main import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://demo", headers={"Authorization": f"Bearer {settings.platform_service_token}"}, timeout=30.0) as c:
        r = await c.request(method, url, json=json)
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, None


async def play(hook: str, params: dict[str, Any], room: Optional[str]) -> None:
    from .agents import manager as agents

    out = await run(hook, params, _asgi_call)
    agent = agents.get("ReportAgent")
    if agent:
        await agent.log(params.get("room") or room, input=f"Démo V2 — geste simulé ({LABELS.get(hook, hook)})", reasoning="Pilote automatique de full_demo_v2 : ce geste, normalement fait par un humain, est joué par l'API de la plateforme (mêmes endpoints, mêmes permissions).", output=out)


def schedule(hook: str, params: dict[str, Any], room: Optional[str]) -> None:
    try:
        asyncio.get_running_loop().create_task(play(hook, dict(params), room), name=f"demo-{hook}")
    except RuntimeError:  # hors boucle (moteur piloté par un test) : le test joue les gestes lui-même
        pass
