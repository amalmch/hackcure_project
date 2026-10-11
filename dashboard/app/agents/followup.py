"""
FollowUpAgent — boucle infirmier :
- entrée du personnel ⇒ risques ouverts de la chambre `in_progress` + `StaffVisit` ;
- sortie ⇒ attente (FOLLOWUP_RECHECK_S), **re-vérification** sur l'état réel de la chambre ⇒ `resolved` + vérifié,
  ou « risque persistant » ⇒ `escalated` + notification du médecin de garde ;
- sans visite dans le délai (critical 2 min, high 10, medium 30) ⇒ escalade ;
- « Marquer résolu » demandé par un soignant ⇒ même vérification différée.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from sqlmodel import select

from ..bus import Event
from ..clinical.news2 import news2
from ..config import settings
from ..db import session_scope
from ..ingest import handler
from ..models import ActionStep, ActionPlan, Risk, StaffVisit
from ..notify import notify
from ..ws import manager
from .base import Agent
from .plans import TYPE_LABELS


def verify_risk(rtype: str, rs: dict[str, Any]) -> tuple[bool, str]:
    """Vérification déterministe sur l'état courant de la chambre. Renvoie (ok, justification)."""
    v = rs.get("vitals") or {}
    posture, activity, expr = rs.get("posture"), rs.get("activity"), rs.get("expression")
    if rtype in ("fall", "local_alarm"):
        ok = posture != "on_floor" and activity != "fall"
        return ok, f"posture {posture}, activité {activity}"
    if rtype == "pain":
        return expr != "pain", f"expression {expr}"
    if rtype in ("unaccompanied_bed_exit", "bed_exit"):
        return posture in ("lying_bed", "sitting_bed"), f"posture {posture}"
    if rtype in ("toilet_too_long", "patient_out_of_room"):
        return posture != "absent", f"posture {posture}"
    if rtype == "call":
        return not rs.get("callPressed"), "appel " + ("toujours actif" if rs.get("callPressed") else "acquitté")
    if rtype == "fever":
        t = v.get("tempC")
        if t is None:
            t = rs.get("skinTempC")
            return (t is None or t < 37.8), f"T° cutanée {t}"
        return t < 38.0, f"T° {t} °C"
    if rtype == "hypothermia":
        return (v.get("tempC") or 36.5) > 35.5, f"T° {v.get('tempC')} °C"
    if rtype == "tachycardia":
        return (v.get("hr") or 0) <= 110, f"FC {v.get('hr')}"
    if rtype == "bradycardia":
        return (v.get("hr") or 70) >= 50, f"FC {v.get('hr')}"
    if rtype == "hypoxemia":
        from ..clinical.spo2 import classify
        from .context import room_is_copd

        c = classify(v.get("spo2"), copd=room_is_copd(str(rs.get("room"))))
        return c["level"] == "none", f"SpO2 {v.get('spo2')} % (cible {c['target']})"
    if rtype == "hypotension":
        return (v.get("sys") or 120) >= 95, f"PAS {v.get('sys')}"  # même seuil que la détection (VitalsAgent)
    if rtype == "hypertension":
        return (v.get("sys") or 120) < 180, f"PAS {v.get('sys')}"
    if rtype == "tachypnea":
        return (v.get("rr") or 16) < 25, f"FR {v.get('rr')}"
    if rtype in ("news2_high", "sepsis_trend"):
        from .context import room_is_copd

        n = news2(rr=v.get("rr"), spo2=v.get("spo2"), on_oxygen=bool((v.get("o2FlowLMin") or 0) > 0), sbp=v.get("sys"), hr=v.get("hr"), temp=v.get("tempC"), spo2_scale2=room_is_copd(str(rs.get("room"))))
        return n.score < 5, f"NEWS2 {n.score}"
    if rtype == "equipment_fault":
        f = rs.get("deviceFaults") or {}
        return not f, ("appareils en service" if not f else "panne persistante : " + ", ".join(x.get("name", k) for k, x in f.items()))
    if rtype == "iv_empty":
        vol = v.get("ivVolumeLeftMl")
        return vol is None or vol > 100, f"volume {vol} ml"
    if rtype == "iv_occlusion":
        return not v.get("ivOcclusion"), "occlusion " + ("présente" if v.get("ivOcclusion") else "levée")
    if rtype == "transfusion_reaction":
        dev = (rs.get("devices") or {}).get(f"{rs.get('room')}-transfusion") or {}
        return not (dev.get("metrics") or {}).get("reaction"), "réaction " + ("présente" if (dev.get("metrics") or {}).get("reaction") else "absente")
    if rtype.startswith("predicted_"):
        from ..clinical.prediction import RISK_TYPES
        from . import manager as _agents

        key = next((k for k, t in RISK_TYPES.items() if t == rtype), None)
        agent = _agents.get("PredictionAgent")
        risk = agent.risk_of(str(rs.get("room")), key) if agent and key else None
        return (risk is None or risk < 60), f"risque prédit {risk if risk is not None else 'non calculé'}/100"
    if rtype == "medication_late":
        from .. import care
        from ..db import session_scope as _scope

        with _scope() as _s:
            late = care.overdue_in_room(_s, str(rs.get("room")))
            labels = ", ".join(d.label for d in late)
        return not late, ("toutes les prises dues sont enregistrées" if not late else f"prise(s) toujours en retard : {labels}")
    if rtype == "behavioral_risk":
        lvl = (rs.get("behavior") or {}).get("risk_level", "none")
        return lvl in ("none", "low"), f"risque comportemental {lvl}"
    if rtype == "thermal_discomfort":
        t = (rs.get("env") or {}).get("tempC")
        return t is None or 19 <= t <= 27, f"ambiance {t} °C"
    return True, "pas de critère automatique : validation du soignant acceptée"


class FollowUpAgent(Agent):
    name = "FollowUpAgent"
    description = "Suit la prise en charge : visite du personnel, re-vérification après son départ, résolution vérifiée ou escalade."
    patterns = ["hackcure/room/+/vision/staff", "hackcure/room/+/vision/state", "internal/risk/created", "internal/risk/resolve_request", "internal/reset"]
    tick_interval = 1.0

    def __init__(self) -> None:
        super().__init__()
        self.pending: dict[int, tuple[float, str]] = {}  # risk_id -> (échéance, origine)
        self.visits: dict[str, int] = {}  # room -> StaffVisit.id en cours
        self.staff_in: dict[str, bool] = {}

    async def handle(self, ev: Event) -> None:
        if ev.topic == "internal/reset":
            self.pending.clear()
            return
        if ev.topic == "internal/risk/resolve_request":
            rid = int(ev.payload["risk_id"])
            self.pending[rid] = (time.time() + settings.followup_recheck_s, f"demande de {ev.payload.get('by', 'soignant')}")
            await self.log(ev.payload.get("room"), input=f"« Marquer résolu » sur le risque #{rid} par {ev.payload.get('by')}", reasoning=f"La résolution est soumise à vérification : re-contrôle de l'état réel dans {settings.followup_recheck_s:.0f} s.", output="vérification planifiée", risk_id=rid)
            return
        if ev.topic == "internal/risk/created":
            await self.join_visit(str(ev.payload.get("room")), int(ev.payload["risk_id"]))
            return
        p = ev.payload
        room, kind, d = p["room"], p["kind"], p["data"]
        if kind == "vision_state":
            present = int(d.get("persons", 1)) > 1
            if present != self.staff_in.get(room, False):
                self.staff_in[room] = present
                if present:
                    await self.on_staff_enter(room, int(d["persons"]), source="vision")
                else:
                    await self.on_staff_leave(room, None, source="vision")
        elif kind == "vision_staff":
            if d["event"] == "staff_enter":
                self.staff_in[room] = True
                await self.on_staff_enter(room, int(d.get("persons", 2)), source="staff")
            else:
                self.staff_in[room] = False
                await self.on_staff_leave(room, d.get("durationSec"), source="staff")

    async def join_visit(self, room: str, rid: int) -> None:
        """Un risque détecté pendant qu'un soignant est déjà dans la chambre est pris en charge par la visite en cours."""
        from ..risks import refresh_room_level, risk_dict

        if room not in self.visits:
            return
        with session_scope() as s:
            r = s.get(Risk, rid)
            if not r or r.status not in ("open", "escalated"):
                return
            r.status = "in_progress"
            r.acknowledged_at = r.acknowledged_at or datetime.now(timezone.utc)
            refresh_room_level(s, room)
            payload = risk_dict(s, r)
        await manager.broadcast({"type": "risk", "event": "in_progress", "risk": payload})
        from .. import n8n

        n8n.release_soon([rid], "personnel dans la chambre", acknowledged=True)
        await self.log(room, input=f"risque #{rid} détecté pendant la visite #{self.visits[room]}", reasoning="Un soignant est déjà dans la chambre : le risque rejoint la prise en charge en cours et sera revérifié à sa sortie.",
                       output=f"#{rid} in_progress", risk_id=rid)

    async def on_staff_enter(self, room: str, persons: int, source: str) -> None:
        from ..risks import open_risks_in_room, refresh_room_level, risk_dict

        if room in self.visits:
            return
        rs = handler.room_state(room)
        rs["callPressed"] = False
        async with self.working("acting"):
            with session_scope() as s:
                risks = open_risks_in_room(s, room)
                top = max(risks, key=lambda r: {"low": 1, "medium": 2, "high": 3, "critical": 4}[r.severity]) if risks else None
                adm_id = top.admission_id if top else None
                visit = StaffVisit(room_code=room, admission_id=adm_id, risk_id=top.id if top else None, persons=persons)
                s.add(visit)
                s.flush()
                self.visits[room] = visit.id
                changed = []
                for r in risks:
                    if r.status in ("open", "escalated"):
                        r.status = "in_progress"
                        r.acknowledged_at = r.acknowledged_at or datetime.now(timezone.utc)
                        self.pending.pop(r.id, None)
                        changed.append(risk_dict(s, r))
                refresh_room_level(s, room)
                vid = visit.id
            for payload in changed:
                await manager.broadcast({"type": "risk", "event": "in_progress", "risk": payload})
            from .. import n8n

            n8n.release_soon([c["id"] for c in changed], "personnel dans la chambre", acknowledged=True)
            await manager.broadcast({"type": "staff_visit", "room": room, "event": "visit_started", "visit_id": vid, "risk_ids": [c["id"] for c in changed]})
            await self.log(room, input=f"personnel détecté ({persons} personnes, source {source})",
                           reasoning=f"{len(risks)} risque(s) ouvert(s) dans la chambre → prise en charge en cours ; visite #{vid} enregistrée.",
                           output=", ".join(f"#{c['id']} in_progress" for c in changed) or "visite sans risque ouvert", risk_id=changed[0]["id"] if changed else None)

    async def on_staff_leave(self, room: str, duration: Any, source: str) -> None:
        vid = self.visits.pop(room, None)
        with session_scope() as s:
            if vid:
                visit = s.get(StaffVisit, vid)
                if visit:
                    visit.ended_at = datetime.now(timezone.utc)
            risks = s.exec(select(Risk).where(Risk.room_code == room, Risk.status == "in_progress")).all()
            ids = [r.id for r in risks]
            n8n_ids = [r.id for r in risks if r.handled_by == "n8n"]
            payload_risks = [{"id": r.id, "type": r.type, "title": r.title, "severity": r.severity} for r in risks if r.handled_by == "n8n"]
        delegated: list[int] = []
        if n8n_ids:
            from .. import n8n

            if n8n.enabled() and await n8n.probe():
                from ..risks import patient_context

                with session_scope() as s:
                    ctx = patient_context(s, room)
                ok = await n8n.send_event("staff-left", {"event": "staff-left", "room": room, "risk_ids": n8n_ids, "risks": payload_risks, "patient": ctx.get("patient"),
                                                         "duration_s": duration, "recheck_seconds": int(settings.followup_recheck_s), "llm_model": settings.llm_model,
                                                         "telegram_chat_id": settings.telegram_chat_id, "platform_url": settings.platform_url, "ts": datetime.now(timezone.utc).isoformat()})
                if ok:
                    delegated = n8n_ids
        due = time.time() + settings.followup_recheck_s
        for rid in ids:
            if rid not in delegated:
                self.pending[rid] = (due, "sortie du personnel")
        await manager.broadcast({"type": "staff_visit", "room": room, "event": "visit_ended", "visit_id": vid, "durationSec": duration})
        if ids or vid:
            local = [i for i in ids if i not in delegated]
            await self.log(room, input=f"sortie du personnel (durée {duration or '?'} s, source {source})",
                           reasoning=f"Fin de visite #{vid}. " + (f"Re-vérification de {len(delegated)} risque(s) déléguée à n8n (workflow risk-verify : attente 2 min, état réel, Claude). " if delegated else "")
                                     + (f"Re-vérification locale de {len(local)} risque(s) dans {settings.followup_recheck_s:.0f} s." if local else ""),
                           output=", ".join(f"#{i}{' (n8n)' if i in delegated else ''}" for i in ids) or "aucun risque à re-vérifier", risk_id=ids[0] if ids else None)

    async def on_tick(self) -> None:
        now = time.time()
        for rid, (due, origin) in list(self.pending.items()):
            if now >= due:
                del self.pending[rid]
                await self.recheck(rid, origin)
        await self.check_escalations()

    async def recheck(self, rid: int, origin: str) -> None:
        from ..risks import refresh_room_level, risk_dict

        async with self.working("thinking"):
            with session_scope() as s:
                risk = s.get(Risk, rid)
                if not risk or risk.status in ("resolved",):
                    return
                room = risk.room_code
                rs = handler.room_state(room)
                ok, why = verify_risk(risk.type, rs)
                plan = s.exec(select(ActionPlan).where(ActionPlan.risk_id == rid).order_by(ActionPlan.id.desc())).first()
                steps = s.exec(select(ActionStep).where(ActionStep.plan_id == plan.id)).all() if plan else []
                done = sum(1 for st in steps if st.done)
                now = datetime.now(timezone.utc)
                if ok:
                    risk.status = "resolved"
                    risk.resolved_at = now
                    risk.verified_at = now
                    risk.resolved_by = f"{self.name} (vérifié — {origin})"
                else:
                    risk.status = "escalated"
                    risk.escalated_at = now
                    risk.notes = (risk.notes + "\n" if risk.notes else "") + f"{now.strftime('%H:%M:%S')} risque persistant après visite : {why}"
                s.flush()
                refresh_room_level(s, room)
                payload = risk_dict(s, risk)
                rtype, sev, title = risk.type, risk.severity, risk.title
            await manager.broadcast({"type": "risk", "event": "resolved" if ok else "escalated", "risk": payload})
            if ok:
                from ..bus import bus

                await bus.publish("internal/risk/resolved", {"risk_id": rid, "room": room, "type": rtype, "by": self.name, "detail": why})
                await self.log(room, input=f"re-vérification #{rid} ({origin}) : {why} ; étapes du plan {done}/{len(steps)}",
                               reasoning=f"Critère de vérification « {TYPE_LABELS.get(rtype, rtype)} » satisfait sur l'état réel de la chambre.",
                               output=f"risque #{rid} résolu et vérifié", risk_id=rid)
                await notify("info", f"Résolu — {title}", f"Vérifié par FollowUpAgent : {why}. Étapes réalisées {done}/{len(steps)}.", room=room, risk_id=rid, target_role="nurse", telegram=False)
            else:
                await self.log(room, input=f"re-vérification #{rid} ({origin}) : {why} ; étapes {done}/{len(steps)}",
                               reasoning="Le critère n'est pas satisfait : risque persistant → escalade au médecin de garde.",
                               output=f"risque #{rid} escaladé", risk_id=rid)
                await notify("critical" if sev == "critical" else "warning", f"Risque persistant — {title}", f"Après passage du personnel : {why}. Escalade au médecin de garde.", room=room, risk_id=rid, target_role="duty_doctor")

    async def check_escalations(self) -> None:
        from ..risks import refresh_room_level, risk_dict

        delays = {"critical": settings.escalation_critical_s, "high": settings.escalation_high_s, "medium": settings.escalation_medium_s}
        now = datetime.now(timezone.utc)
        escalated = []
        with session_scope() as s:
            for risk in s.exec(select(Risk).where(Risk.status == "open")).all():
                limit = delays.get(risk.severity)
                if limit is None or risk.escalated_at is not None or risk.handled_by == "n8n":
                    continue  # les risques orchestrés par n8n sont escaladés par le nœud Wait du workflow
                det = risk.detected_at if risk.detected_at.tzinfo else risk.detected_at.replace(tzinfo=timezone.utc)
                if (now - det).total_seconds() >= limit and not self.staff_in.get(risk.room_code):
                    risk.status = "escalated"
                    risk.escalated_at = now
                    risk.notes = (risk.notes + "\n" if risk.notes else "") + f"{now.strftime('%H:%M:%S')} aucune visite sous {limit:.0f} s"
                    s.flush()
                    refresh_room_level(s, risk.room_code)
                    escalated.append((risk_dict(s, risk), limit))
        for payload, limit in escalated:
            await manager.broadcast({"type": "risk", "event": "escalated", "risk": payload})
            await self.log(payload["room"], input=f"risque #{payload['id']} [{payload['severity']}] sans visite depuis {limit:.0f} s",
                           reasoning="Délai de prise en charge dépassé (critical 2 min, high 10 min, medium 30 min) : escalade.",
                           output=f"risque #{payload['id']} escaladé, médecin de garde notifié", risk_id=payload["id"])
            await notify("critical" if payload["severity"] == "critical" else "warning", f"Escalade — {payload['title']}", f"Aucune intervention en {limit / 60:.0f} min. Médecin de garde sollicité.", room=payload["room"], risk_id=payload["id"], target_role="duty_doctor")
