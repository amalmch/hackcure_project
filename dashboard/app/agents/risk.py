"""
RiskAgent — reçoit les candidats des autres agents, fixe la sévérité de façon **déterministe** (règles + NEWS2),
déduplique, crée le risque **immédiatement** (notification infirmier ≥ medium, médecin de garde ≥ high,
in-app + Telegram), puis l'enrichit : explication et plan d'action JSON (3–6 étapes) par le LLM, avec plan
de secours prédéfini par type.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import select

from ..bus import Event, bus
from ..config import settings
from ..db import session_scope
from ..ingest import handler
from ..models import ActionPlan, ActionStep, Risk
from ..notify import notify
from ..ws import manager
from .base import Agent, Stopwatch
from .context import current_news2, room_vitals
from .llm import get_llm, load_prompt
from .plans import FALLBACK_PLANS, TYPE_LABELS, severity_for

SEV_LABEL = {"low": "FAIBLE", "medium": "MOYEN", "high": "ÉLEVÉ", "critical": "CRITIQUE"}
NOTIF_LEVEL = {"low": "info", "medium": "warning", "high": "warning", "critical": "critical"}
# V2 : seul un risque d'AMBIANCE se lève seul. Un risque clinique n'est résolu que par la boucle soignant
# (prise en charge → intervention → sortie → revérification déterministe par FollowUpAgent / n8n risk-verify).
AUTO_CLEARABLE = {"thermal_discomfort", "room_overheat"}


class RiskAgent(Agent):
    name = "RiskAgent"
    description = "Qualifie chaque risque (sévérité déterministe), le déduplique, notifie et rédige explication + plan d'action (LLM ou plan de secours)."
    patterns = ["internal/risk_candidate", "internal/risk_clear", "internal/reset"]

    async def on_start(self) -> None:
        try:
            with session_scope() as s:
                from ..risks import refresh_all_levels

                refresh_all_levels(s)
        except Exception:
            pass

    async def handle(self, ev: Event) -> None:
        if ev.topic == "internal/reset":
            return
        if ev.topic == "internal/risk_clear":
            await self.on_clear(ev.payload)
            return
        await self.on_candidate(ev.payload)

    # ── création ────────────────────────────────────────────────────────────
    async def on_candidate(self, c: dict[str, Any]) -> None:
        from ..risks import patient_context, recent_resolved_same, refresh_room_level, risk_dict

        room, rtype = c["room"], c["type"]
        details = dict(c.get("details") or {})
        sw = Stopwatch()
        async with self.working("thinking"):
            with session_scope() as s:
                ctx = patient_context(s, room)
                patient = ctx.get("patient") or {}
                n2 = current_news2(room)
                if n2 is not None:
                    details.setdefault("news2", n2.score)
                severity = severity_for(rtype, details, patient)
                title = f"{TYPE_LABELS.get(rtype, rtype)} — chambre {room}"
                # déduplication : même type encore ouvert dans la chambre
                existing = s.exec(select(Risk).where(Risk.room_code == room, Risk.type == rtype, Risk.status.in_(("open", "in_progress", "escalated")))).first()
                if existing:
                    bumped = False
                    if {"low": 1, "medium": 2, "high": 3, "critical": 4}[severity] > {"low": 1, "medium": 2, "high": 3, "critical": 4}[existing.severity]:
                        existing.severity = severity
                        bumped = True
                    existing.notes = (existing.notes + "\n" if existing.notes else "") + f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} signal répété par {c.get('source_agent')} : {json.dumps(details, ensure_ascii=False)[:200]}"
                    s.flush()
                    if bumped:
                        refresh_room_level(s, room)
                    dup = (existing.id, existing.status, bumped, risk_dict(s, existing))
                else:
                    dup = None
            # hors de la session : ne jamais garder une transaction d'écriture ouverte pendant un await (SQLite se verrouille)
            if dup is not None:
                rid, status, bumped, payload = dup
                await self.log(room, input=f"candidat {rtype} ({c.get('source_agent')}) : {json.dumps(details, ensure_ascii=False)[:300]}",
                               reasoning=f"Un risque « {TYPE_LABELS.get(rtype, rtype)} » est déjà {status} (#{rid}) : dédupliqué" + (", sévérité relevée" if bumped else "") + ".",
                               output=f"risque #{rid} mis à jour (pas de doublon)", risk_id=rid, duration_ms=sw.ms)
                await manager.broadcast({"type": "risk", "event": "updated", "risk": payload})
                return
            with session_scope() as s:
                recent = recent_resolved_same(s, room, rtype, minutes=1)
                risk = Risk(
                    admission_id=ctx.get("admission_id"), room_code=room, type=rtype, title=title, severity=severity, status="open",
                    source_agent=c.get("source_agent", "?"), news2=details.get("news2"), dedup_key=f"{room}:{rtype}",
                    explanation=self.deterministic_explanation(rtype, severity, details, patient),
                    notes=("Récidive moins d'une minute après résolution." if recent else ""),
                )
                s.add(risk)
                s.flush()
                rid = risk.id
                refresh_room_level(s, room)
                payload = risk_dict(s, risk)
                treatments = ctx.get("treatments", "")
            # 1) le risque existe : diffusion immédiate (avant le LLM)
            await manager.broadcast({"type": "risk", "event": "created", "risk": payload})
            await bus.publish("internal/risk/created", {"risk_id": rid, "room": room, "type": rtype, "severity": severity})
            # 2) orchestration : n8n (risk-triage) si joignable, sinon agents locaux
            delegated = await self.delegate_to_n8n(rid, room)
            await self.notify_for(rid, room, rtype, severity, payload["explanation"], patient, telegram=not delegated)
            await self.log(room, input=f"candidat {rtype} ({c.get('source_agent')}) : {json.dumps(details, ensure_ascii=False)[:300]}",
                           reasoning=f"Règles déterministes → sévérité {severity}" + (f" ; NEWS2 {details.get('news2')}" if details.get("news2") is not None else "") + f" ; patient {patient.get('full_name', '?')} (risque de chute {patient.get('fall_risk', '?')}). "
                                     + ("Risque délégué à n8n (workflow risk-triage : plan Claude, Telegram, attente d'acquittement, escalade)." if delegated else "n8n indisponible ou désactivé : traitement local (LLM + notifications + escalade par le FollowUpAgent)."),
                           output=f"risque #{rid} « {title} » [{severity}] créé — " + ("orchestré par n8n" if delegated else "agents locaux"), risk_id=rid, duration_ms=sw.ms)
        if delegated:
            return
        # 3) enrichissement LLM local (explication + plan)
        await self.enrich(rid, room, rtype, severity, details, patient, treatments)

    async def delegate_to_n8n(self, rid: int, room: str) -> bool:
        from .. import n8n
        from ..risks import n8n_payload

        if not n8n.enabled() or not await n8n.probe():
            return False
        with session_scope() as s:
            risk = s.get(Risk, rid)
            if not risk:
                return False
            payload = n8n_payload(s, risk)
        ok = await n8n.send_event("risk-created", payload)
        if ok:
            with session_scope() as s:
                risk = s.get(Risk, rid)
                if risk:
                    risk.handled_by = "n8n"
        return ok

    @staticmethod
    def deterministic_explanation(rtype: str, severity: str, details: dict[str, Any], patient: dict[str, Any]) -> str:
        vals = ", ".join(f"{k} = {v}" for k, v in details.items() if v is not None and k != "components")
        who = f"{patient.get('full_name')} ({patient.get('age')} ans)" if patient else "patient inconnu"
        return f"{TYPE_LABELS.get(rtype, rtype)} [{SEV_LABEL[severity]}] pour {who}. Valeurs observées : {vals or 'n/a'}. Analyse détaillée en cours."

    async def notify_for(self, rid: int, room: str, rtype: str, severity: str, explanation: str, patient: dict[str, Any], telegram: bool = True) -> None:
        """In-app toujours ; Telegram seulement si n8n ne s'en charge pas."""
        if severity == "low":
            return
        label = TYPE_LABELS.get(rtype, rtype)
        title = f"[{SEV_LABEL[severity]}] {label} — chambre {room}"
        body = f"{patient.get('full_name', 'Patient')} · {explanation[:220]}"
        await notify(NOTIF_LEVEL[severity], title, body, room=room, risk_id=rid, target_role="nurse", telegram=telegram)
        if severity in ("high", "critical"):
            await notify(NOTIF_LEVEL[severity], f"Médecin de garde — {title}", body, room=room, risk_id=rid, target_role="duty_doctor", telegram=telegram)

    async def enrich(self, rid: int, room: str, rtype: str, severity: str, details: dict[str, Any], patient: dict[str, Any], treatments: str) -> None:
        from ..risks import risk_dict

        sw = Stopwatch()
        llm = get_llm()
        context = {
            "task": "risk_plan", "room": room, "risk_type": rtype, "risk_label": TYPE_LABELS.get(rtype, rtype), "severity": severity, "details": details,
            "patient": patient, "treatments": treatments, "vitals": room_vitals(room), "news2": details.get("news2"),
            "room_state": {k: handler.room_state(room).get(k) for k in ("posture", "activity", "expression", "skinTempC", "persons")},
            "env": handler.room_state(room).get("env"),
        }
        async with self.working("thinking"):
            result = await llm.complete_json(load_prompt("_system"), load_prompt("risk_plan", context=json.dumps(context, ensure_ascii=False, default=str)))
            provider = llm.name
            steps: list[dict[str, Any]] = []
            explanation: Optional[str] = None
            if result and isinstance(result.get("steps"), list):
                steps = [{"text": str(st.get("text") if isinstance(st, dict) else st)} for st in result["steps"] if (st.get("text") if isinstance(st, dict) else st)]
                explanation = str(result.get("explanation") or "").strip() or None
            fallback = not 3 <= len(steps) <= 6
            if fallback:
                from .llm import FALLBACK_LABEL

                steps = [dict(x) for x in FALLBACK_PLANS.get(rtype, FALLBACK_PLANS["default"])][:6]
                provider = FALLBACK_LABEL if provider != "mock" else "mock"
            with session_scope() as s:
                risk = s.get(Risk, rid)
                if not risk:
                    return
                if explanation:
                    risk.explanation = explanation
                plan = ActionPlan(risk_id=rid, summary=f"Plan d'action — {TYPE_LABELS.get(rtype, rtype)} ({severity})", created_by=self.name, llm_provider=provider)
                s.add(plan)
                s.flush()
                for i, st in enumerate(steps, start=1):
                    s.add(ActionStep(plan_id=plan.id, order=i, text=st["text"], suggested_by_ai=True))
                s.flush()
                payload = risk_dict(s, risk)
            await manager.broadcast({"type": "risk", "event": "updated", "risk": payload})
            await self.log(room, input=f"contexte LLM : {json.dumps({k: context[k] for k in ('risk_type', 'severity', 'vitals', 'news2')}, ensure_ascii=False, default=str)[:400]}",
                           reasoning=(f"{provider.upper()} : plan prédéfini par type de risque, explication déterministe conservée." if fallback else f"LLM {provider} : explication citant les valeurs mesurées, allergies ({patient.get('allergies') or 'aucune'}) et traitements respectés ; plan de {len(steps)} étapes à valider par un soignant."),
                           status="ok" if not fallback else "error",
                           output=(explanation or payload["explanation"])[:300] + f" | {len(steps)} étapes", risk_id=rid, duration_ms=sw.ms)

    # ── levée automatique (valeurs normalisées) ─────────────────────────────
    async def on_clear(self, c: dict[str, Any]) -> None:
        from ..risks import refresh_room_level, risk_dict

        room, types, reason = c["room"], c.get("types") or [], c.get("reason", "")
        changed = []
        with session_scope() as s:
            noted = []
            for rtype in types:
                risk = s.exec(select(Risk).where(Risk.room_code == room, Risk.type == rtype, Risk.status == "open")).first()
                if not risk:
                    continue
                if rtype not in AUTO_CLEARABLE:
                    # risque clinique : on trace la normalisation du signal, le risque reste ouvert jusqu'à validation par un soignant
                    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
                    if "signal revenu dans les limites" not in (risk.notes or "")[-160:]:
                        risk.notes = (risk.notes + "\n" if risk.notes else "") + f"{stamp} signal revenu dans les limites ({reason}) — à confirmer par un soignant"
                        s.flush()
                        noted.append(risk_dict(s, risk))
                    continue
                risk.status = "resolved"
                risk.resolved_at = datetime.now(timezone.utc)
                risk.verified_at = risk.resolved_at
                risk.resolved_by = f"{self.name} (auto : {reason})"
                s.flush()
                changed.append(risk_dict(s, risk))
            if changed:
                refresh_room_level(s, room)
        for payload in noted:
            await manager.broadcast({"type": "risk", "event": "updated", "risk": payload})
            await self.log(room, input=f"signal normalisé : {payload['type']} — {reason}", reasoning="Risque clinique : la normalisation d'un signal ne suffit pas. Le risque reste ouvert jusqu'à la prise en charge par un soignant et la revérification.",
                           output=f"risque #{payload['id']} maintenu (note ajoutée)", risk_id=payload["id"])
        for payload in changed:
            await manager.broadcast({"type": "risk", "event": "resolved", "risk": payload})
        if changed:
            from .. import n8n

            n8n.release_soon([p["id"] for p in changed], "signal normalisé (levée automatique)")
            await self.log(room, input=f"levée : {payload['type']} — {reason}", reasoning="Risque d'ambiance (non clinique) revenu dans les limites : clôturé automatiquement.", output=f"risque #{payload['id']} résolu", risk_id=payload["id"])
