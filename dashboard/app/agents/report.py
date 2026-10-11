"""
ReportAgent — rapport de garde (par chambre : événements, risques, actions, état, humeur) et brouillon
de rapport médecin, rédigés par le LLM (ou le mock) à partir des données en base uniquement.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlmodel import select

from ..db import session_scope
from ..ingest import handler
from ..models import ActionPlan, ActionStep, Admission, MedicalReport, MoodObservation, Patient, PatientStateSnapshot, Risk, ShiftReport
from .base import Agent, Stopwatch
from .context import current_news2, room_vitals
from .llm import get_llm, load_prompt
from .plans import TYPE_LABELS

MOOD_FR = {"calm": "calme", "anxious": "anxieux", "pain": "douloureux", "sad": "triste", "agitated": "agité", "neutral": "neutre", "happy": "serein", "surprised": "surpris"}


class ReportAgent(Agent):
    name = "ReportAgent"
    description = "Rédige le rapport de garde (événements, risques, actions, état, humeur par chambre) et les brouillons de rapport médecin."
    patterns = ["internal/report_request"]
    tick_interval = 3600.0

    def shift_context(self, s, start: datetime, end: datetime) -> dict[str, Any]:
        from ..risks import patient_context

        rooms = []
        for room in handler.ROOMS:
            ctx = patient_context(s, room)
            rs = handler.room_state(room)
            risks = s.exec(select(Risk).where(Risk.room_code == room, Risk.detected_at >= start, Risk.detected_at <= end).order_by(Risk.detected_at)).all()
            actions = []
            for r in risks:
                for plan in s.exec(select(ActionPlan).where(ActionPlan.risk_id == r.id)).all():
                    for st in s.exec(select(ActionStep).where(ActionStep.plan_id == plan.id, ActionStep.done.is_(True))).all():
                        actions.append(f"{st.text} ({st.done_by or '?'} {st.done_at.strftime('%H:%M') if st.done_at else ''})")
            snaps = s.exec(select(PatientStateSnapshot).where(PatientStateSnapshot.room_code == room, PatientStateSnapshot.ts >= start, PatientStateSnapshot.ts <= end).order_by(PatientStateSnapshot.ts)).all()
            events, last = [], None
            for sn in snaps:
                key = (sn.posture, sn.activity)
                if key != last:
                    events.append(f"{sn.ts.strftime('%H:%M')} {sn.posture}/{sn.activity}")
                    last = key
            moods = s.exec(select(MoodObservation).where(MoodObservation.room_code == room, MoodObservation.ts >= start, MoodObservation.ts <= end).order_by(MoodObservation.ts.desc())).all()
            mood_txt = None
            if moods:
                counts: dict[str, int] = {}
                for m in moods:
                    counts[m.mood] = counts.get(m.mood, 0) + 1
                dominant = max(counts, key=counts.get)
                mood_txt = f"{MOOD_FR.get(dominant, dominant)} (dominante sur {len(moods)} observations ; dernière : {MOOD_FR.get(moods[0].mood, moods[0].mood)} à {moods[0].ts.strftime('%H:%M')})"
            p = ctx.get("patient")
            rooms.append({
                "room": room, "patient": (f"{p['full_name']} ({p['code']}, {p['age']} ans)" if p else None),
                "posture": rs.get("posture"), "activity": rs.get("activity"), "expression": rs.get("expression"), "vitals": room_vitals(room),
                "news2": (current_news2(room).score if current_news2(room) else None), "mood": mood_txt,
                "risks": [{"id": r.id, "title": TYPE_LABELS.get(r.type, r.type), "severity": r.severity, "status": r.status, "at": r.detected_at.strftime("%H:%M"), "resolved_by": r.resolved_by} for r in risks],
                "actions": actions, "events": events,
            })
        return {"task": "shift_report", "period": f"{start.astimezone().strftime('%d/%m %H:%M')} → {end.astimezone().strftime('%d/%m %H:%M')}", "rooms": rooms}

    async def generate_shift_report(self, start: Optional[datetime] = None, end: Optional[datetime] = None, author: str = "ReportAgent") -> int:
        """Renvoie l'identifiant du ShiftReport créé."""
        end = end or datetime.now(timezone.utc)
        start = start or (end - timedelta(hours=12))
        sw = Stopwatch()
        async with self.working("thinking"):
            with session_scope() as s:
                ctx = self.shift_context(s, start, end)
            llm = get_llm()
            result = await llm.complete_json(load_prompt("_system"), load_prompt("shift_report", context=json.dumps(ctx, ensure_ascii=False, default=str)), max_tokens=1800)
            md = (result or {}).get("markdown") if result else None
            provider = llm.name
            if not md:
                from .llm import MockLlm

                md = MockLlm()._shift_report(ctx)
                from .llm import FALLBACK_LABEL

                provider = FALLBACK_LABEL if provider != "mock" else "mock"
            with session_scope() as s:
                rep = ShiftReport(shift_start=start, shift_end=end, author=author, content=md, status="draft")
                s.add(rep)
                s.flush()
                rid = rep.id
            await self.log(None, input=f"rapport de garde {ctx['period']} ({sum(len(r['risks']) for r in ctx['rooms'])} risques, {sum(len(r['events']) for r in ctx['rooms'])} événements)",
                           reasoning=f"Synthèse par chambre (état, constantes mesurées, risques, actions cochées, humeur) rédigée par {provider} ; brouillon à valider.",
                           output=f"ShiftReport #{rid} créé ({len(md)} caractères)", duration_ms=sw.ms)
        return rid

    async def draft_medical_report(self, admission_id: int, author: str) -> int:
        """Renvoie l'identifiant du MedicalReport (brouillon) créé."""
        from ..risks import patient_context

        sw = Stopwatch()
        async with self.working("thinking"):
            with session_scope() as s:
                adm = s.get(Admission, admission_id)
                if not adm:
                    raise ValueError("Admission introuvable")
                p = s.get(Patient, adm.patient_id)
                ctx = patient_context(s, adm.room_code) if adm.discharged_at is None else {"treatments": ""}
                risks = s.exec(select(Risk).where(Risk.admission_id == admission_id).order_by(Risk.detected_at)).all()
                context = {
                    "task": "medical_report",
                    "patient": {"full_name": p.full_name, "code": p.code, "age": p.age, "sex": p.sex, "blood_group": p.blood_group, "allergies": p.allergies, "history": p.history},
                    "admission": {"admitted_at": adm.admitted_at.strftime("%d/%m/%Y"), "room_code": adm.room_code, "reason": adm.reason, "referring_doctor": adm.referring_doctor},
                    "treatments": ctx.get("treatments", ""), "vitals": room_vitals(adm.room_code) if adm.discharged_at is None else {},
                    "news2": (current_news2(adm.room_code).score if adm.discharged_at is None and current_news2(adm.room_code) else None),
                    "risks": [{"title": TYPE_LABELS.get(r.type, r.type), "severity": r.severity, "status": r.status, "at": r.detected_at.strftime("%d/%m %H:%M")} for r in risks],
                }
            llm = get_llm()
            result = await llm.complete_json(load_prompt("_system"), load_prompt("medical_report", context=json.dumps(context, ensure_ascii=False, default=str)), max_tokens=1500)
            content = (result or {}).get("content") if result else None
            provider = llm.name
            if not content:
                from .llm import MockLlm

                content = MockLlm()._medical_report(context)
                from .llm import FALLBACK_LABEL

                provider = FALLBACK_LABEL if provider != "mock" else "mock"
            with session_scope() as s:
                rep = MedicalReport(admission_id=admission_id, author=author, title="Compte rendu médical (brouillon IA)", content=content, status="draft", ai_draft=True)
                s.add(rep)
                s.flush()
                rid = rep.id
            await self.log(context["admission"]["room_code"], input=f"brouillon de rapport médecin pour l'admission #{admission_id}", reasoning=f"Rédigé par {provider} à partir des données du dossier uniquement ; sections manquantes marquées « à compléter ».", output=f"MedicalReport #{rid} (brouillon)", duration_ms=sw.ms)
        return rid
