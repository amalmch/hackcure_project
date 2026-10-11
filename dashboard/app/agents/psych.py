"""
PsychAgent (V2, étape 7) — état psychologique des patients.

- Questionnaire d'admission (PHQ-9, GAD-7, sommeil) proposé sur tablette dès que le patient est installé au lit.
- Score continu de bien-être (0–100) et niveau de risque pour 3 troubles (dépression, anxiété généralisée,
  insomnie), calculés par `clinical/psych.compute` à partir des questionnaires, des expressions du visage, des
  levers et passages aux toilettes la nuit, du sommeil, des constantes et des antécédents du dossier.
- Item 9 du PHQ-9 positif ⇒ alerte immédiate au psychiatre et au médecin de garde.
- Score sous le seuil ⇒ notification aux infirmiers, au psychiatre et au médecin généraliste, avec conduite à tenir.
Ce n'est jamais un diagnostic. Le workflow n8n `psych-monitoring` rédige l'explication des facteurs.
"""

from __future__ import annotations

import json
import secrets
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import select

from .. import orchestration
from ..bus import Event, bus
from ..clinical import psych as rules
from ..config import settings
from ..db import session_scope
from ..ingest import handler
from ..models import Admission, MedicalRecordEntry, Patient, PsychQuestionnaire, PsychScore
from ..notify import notify
from ..ws import manager
from .base import Agent
from .context import is_night, room_vitals

ALERT_ROLES = ("nurse", "psychiatrist", "general_doctor")
esc = lambda t: str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731


class RoomSignals:
    """Observations d'une chambre accumulées en mémoire (remises à zéro au redémarrage et au reset)."""

    def __init__(self) -> None:
        self.expr: deque[str] = deque(maxlen=240)
        self.behavior: deque[str] = deque(maxlen=120)  # indicateurs de l'analyse comportementale (vision)
        self.night_exits = 0
        self.night_toilets = 0
        self.night_s = 0.0
        self.sleep_s = 0.0
        self.posture: Optional[str] = None
        self.activity: Optional[str] = None
        self.last_ts = time.time()

    def counts(self) -> dict[str, int]:
        return {"sad": sum(1 for e in self.expr if e == "sad"), "pain": sum(1 for e in self.expr if e == "pain"), "fear": sum(1 for e in self.expr if e in ("fear", "anger")), "total": len(self.expr)}

    def behavior_counts(self) -> dict[str, int]:
        return {"agitation": sum(1 for b in self.behavior if "agitation" in b), "immobility": sum(1 for b in self.behavior if "immobility" in b), "instability": sum(1 for b in self.behavior if "instability" in b)}

    def sleep_hours(self) -> Optional[float]:
        return round(8.0 * self.sleep_s / self.night_s, 1) if self.night_s >= 60 else None


def questionnaire_out(q: PsychQuestionnaire, with_answers: bool = True) -> dict[str, Any]:
    iso = lambda d: (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).isoformat() if d else None  # noqa: E731
    d = {"id": q.id, "status": q.status, "created_at": iso(q.created_at), "completed_at": iso(q.completed_at), "scores": json.loads(q.scores_json or "{}"), "q9_positive": q.q9_positive,
         "url": f"/patient/questionnaire/{q.token}"}
    if with_answers:
        d["answers"] = json.loads(q.answers_json or "{}")
    return d


def score_out(s: PsychScore) -> dict[str, Any]:
    ts = s.ts if s.ts.tzinfo else s.ts.replace(tzinfo=timezone.utc)
    return {"id": s.id, "ts": ts.isoformat(), "wellbeing": s.wellbeing, "level": s.level, **json.loads(s.detail_json or "{}")}


class PsychAgent(Agent):
    name = "PsychAgent"
    description = "Propose le questionnaire d'admission et suit le bien-être psychologique (dépression, anxiété, insomnie) à partir des questionnaires, de la vision, du sommeil et des constantes. Jamais un diagnostic."
    patterns = ["hackcure/room/+/vision/state", "hackcure/room/+/vision/expression", "internal/psych/questionnaire", "internal/behavior", "internal/reset"]

    def __init__(self) -> None:
        super().__init__()
        self.tick_interval = settings.psych_tick_s
        self.rooms: dict[str, RoomSignals] = {}
        self.last: dict[str, tuple[int, str]] = {}
        self.alerted: dict[str, float] = {}

    def sig(self, room: str) -> RoomSignals:
        if room not in self.rooms:
            self.rooms[room] = RoomSignals()
        return self.rooms[room]

    async def handle(self, ev: Event) -> None:
        if ev.topic == "internal/reset":
            self.rooms.clear()
            self.last.clear()
            self.alerted.clear()
            return
        if ev.topic == "internal/psych/questionnaire":
            await self.on_questionnaire(int(ev.payload["id"]))
            return
        if ev.topic == "internal/behavior":  # risque comportemental (pipeline de vision) : agitation, immobilité prolongée…
            self.sig(str(ev.payload["room"])).behavior.extend(str(i) for i in (ev.payload.get("indicators") or []))
            return
        room, kind, d = ev.payload["room"], ev.payload["kind"], ev.payload["data"]
        s = self.sig(room)
        if kind == "vision_expression":
            if float(d.get("confidence", 0)) >= 0.4:
                s.expr.append(d["expression"])
            return
        now, night = time.time(), is_night()
        dt = min(5.0, max(0.0, now - s.last_ts))
        s.last_ts = now
        if night:
            s.night_s += dt
            if d.get("activity") == "sleeping":
                s.sleep_s += dt
            if d.get("posture") in ("standing", "walking") and s.posture in ("lying_bed", "sitting_bed", None) and s.posture != d.get("posture"):
                s.night_exits += 1
            if d.get("activity") == "toilet" and s.activity != "toilet":
                s.night_toilets += 1
        s.posture, s.activity = d.get("posture"), d.get("activity")

    # ── questionnaire d'admission ────────────────────────────────────────────
    async def ensure_questionnaire(self, room: str) -> None:
        rs = handler.room_state(room)
        if rs.get("posture") not in ("lying_bed", "sitting_bed"):
            return  # le patient n'est pas encore installé au lit
        with session_scope() as s:
            adm = s.exec(select(Admission).where(Admission.room_code == room, Admission.discharged_at.is_(None))).first()
            if not adm or s.exec(select(PsychQuestionnaire.id).where(PsychQuestionnaire.admission_id == adm.id)).first():
                return
            p = s.get(Patient, adm.patient_id)
            q = PsychQuestionnaire(patient_pk=p.id, admission_id=adm.id, room_code=room, token=secrets.token_urlsafe(12))
            s.add(q)
            s.flush()
            out, name, pid = questionnaire_out(q, False), p.full_name, p.patient_id
        await manager.broadcast({"type": "psych", "event": "questionnaire_created", "patient_id": pid, "room": room, "questionnaire": out})
        await notify("info", f"Questionnaire d'admission — chambre {room}", f"{name} est installé(e) : proposer le questionnaire de bien-être sur la tablette ({settings.platform_url}{out['url']}).", room=room, target_role="nurse", telegram=False)
        await self.log(room, input=f"{name} installé(e) au lit (admission en cours)", reasoning="Questionnaire d'admission créé : PHQ-9 (humeur), GAD-7 (inquiétudes) et sommeil, à remplir par le patient sur tablette.", output=f"lien tablette {out['url']}")

    async def on_questionnaire(self, qid: int) -> None:
        """Questionnaire rempli : alerte immédiate si l'item 9 du PHQ-9 est positif, puis recalcul du score."""
        with session_scope() as s:
            q = s.get(PsychQuestionnaire, qid)
            if not q:
                return
            p = s.get(Patient, q.patient_pk)
            room, name, scores, q9 = q.room_code, p.full_name, json.loads(q.scores_json or "{}"), q.q9_positive
        await self.log(room, input=f"questionnaire d'admission rempli par {name}", reasoning=f"PHQ-9 {scores['phq9']['score']}/27 ({scores['phq9']['level']}), GAD-7 {scores['gad7']['score']}/21 ({scores['gad7']['level']}), sommeil {scores['sleep']['score']}/18 ({scores['sleep']['level']})."
                       + (" ITEM 9 POSITIF : alerte immédiate, quel que soit le score total." if q9 else ""), output="alerte psychiatre + médecin de garde" if q9 else "score de bien-être recalculé", status="error" if q9 else "ok")
        if q9:
            body = f"{name} déclare des idées de mort ou d'automutilation (PHQ-9, item 9 = {scores['q9']}/3). " + " ".join(rules.Q9_CONDUCT[:2])
            for role in ("psychiatrist", "duty_doctor", "nurse"):
                await notify("critical", f"ALERTE — idées suicidaires déclarées, chambre {room}", body, room=room, target_role=role, telegram=False)
            await bus.publish("internal/risk_candidate", {"room": room, "type": "psych_alert", "source_agent": self.name, "details": {"phq9_item9": scores["q9"], "phq9": scores["phq9"]["score"]}})
            from ..notify.telegram import send_telegram

            await send_telegram(f"🚨 <b>ALERTE PSYCHIATRIQUE — chambre {esc(room)}</b>\n{esc(body)}\n<i>Psychiatre et médecin de garde prévenus.</i>")
        await self.evaluate(room, force=True)

    # ── score continu ────────────────────────────────────────────────────────
    async def on_tick(self) -> None:
        for room in handler.ROOMS:
            await self.ensure_questionnaire(room)
            await self.evaluate(room)

    async def evaluate(self, room: str, force: bool = False) -> None:
        sig = self.sig(room)
        with session_scope() as s:
            adm = s.exec(select(Admission).where(Admission.room_code == room, Admission.discharged_at.is_(None))).first()
            if not adm:
                return
            p = s.get(Patient, adm.patient_id)
            q = s.exec(select(PsychQuestionnaire).where(PsychQuestionnaire.admission_id == adm.id, PsychQuestionnaire.status == "completed").order_by(PsychQuestionnaire.id.desc())).first()
            psy_hist = " ".join(e.content for e in s.exec(select(MedicalRecordEntry).where(MedicalRecordEntry.patient_pk == p.id, MedicalRecordEntry.type == "psychologie")).all())
            inp = {"questionnaire": json.loads(q.scores_json) if q else None, "expr": sig.counts(), "night_exits": sig.night_exits, "night_toilets": sig.night_toilets, "sleep_hours": sig.sleep_hours(),
                   "behavior": sig.behavior_counts(), "vitals": room_vitals(room), "history": f"{p.history} {psy_hist}"}
            res = rules.compute(inp)
            prev = self.last.get(room)
            if not force and prev and abs(prev[0] - res["wellbeing"]) < 3 and prev[1] == res["level"]:
                return
            self.last[room] = (res["wellbeing"], res["level"])
            detail = {k: res[k] for k in ("depression", "anxiety", "insomnia")}
            detail.update(conduct=rules.conduct(res), inputs={"night_exits": sig.night_exits, "night_toilets": sig.night_toilets, "sleep_hours": sig.sleep_hours(), "expressions": sig.counts(), "behavior": sig.behavior_counts(), "questionnaire": bool(q)}, q9_positive=res["q9_positive"])
            row = PsychScore(patient_pk=p.id, admission_id=adm.id, room_code=room, wellbeing=res["wellbeing"], level=res["level"], detail_json=json.dumps(detail, ensure_ascii=False))
            s.add(row)
            s.flush()
            out, pid, name, sid = score_out(row), p.patient_id, p.full_name, row.id
        await manager.broadcast({"type": "psych", "event": "score", "patient_id": pid, "room": room, "score": out})
        low = res["wellbeing"] < settings.psych_threshold
        if low and time.time() - self.alerted.get(room, 0) > 600:
            self.alerted[room] = time.time()
            worst = max(("depression", "anxiety", "insomnia"), key=lambda k: res[k]["score"])
            body = f"{name} : score de bien-être {res['wellbeing']}/100. Risque le plus marqué : {rules.LABELS[worst].lower()} ({res[worst]['level']}) — {'; '.join(res[worst]['factors'][:3])}. Conduite à tenir : {out['conduct'][0]}"
            for role in ALERT_ROLES:
                await notify("warning", f"Bien-être psychologique bas — chambre {room}", body, room=room, target_role=role, telegram=False)
            await bus.publish("internal/risk_candidate", {"room": room, "type": "psych_low_wellbeing", "source_agent": self.name, "details": {"wellbeing": res["wellbeing"], "worst": rules.LABELS[worst], "level": res[worst]["level"]}})
            ctx = {"task": "psych_monitoring", "chambre": room, "patient": {"nom": name, "antecedents": inp["history"][:600]}, "score_bien_etre": res["wellbeing"], "seuil": settings.psych_threshold,
                   "troubles": {rules.LABELS[k]: {"score": res[k]["score"], "niveau": res[k]["level"], "facteurs": res[k]["factors"]} for k in ("depression", "anxiety", "insomnia")},
                   "observations": detail["inputs"], "conduite_a_tenir_standard": out["conduct"]}
            path = await orchestration.ask("psych-monitoring", str(sid), ctx, room=room)
            await self.log(room, input=f"score de bien-être {res['wellbeing']}/100 (seuil {settings.psych_threshold})", reasoning=f"Sous le seuil : {rules.LABELS[worst]} {res[worst]['level']} ({'; '.join(res[worst]['factors'][:3])}). Infirmiers, psychiatre et médecin généraliste notifiés ; explication demandée "
                           + ("au workflow n8n psych-monitoring." if path == "n8n" else "au LLM local.") + " Ce n'est pas un diagnostic.", output="alerte psychologique + conduite à tenir", status="error")


@orchestration.handler("psych-monitoring")
async def on_psych_explanation(ref: str, result: dict[str, Any], meta: dict[str, Any]) -> Optional[str]:
    with session_scope() as s:
        row = s.get(PsychScore, int(ref))
        if not row:
            return None
        detail = json.loads(row.detail_json or "{}")
        detail["ai"] = {"explanation": str(result.get("explanation") or "")[:1200], "conduct": [str(x)[:240] for x in (result.get("conduct") or [])][:5], "provider": meta.get("provider") or "anthropic (n8n)", "fallback": bool(meta.get("fallback"))}
        row.detail_json = json.dumps(detail, ensure_ascii=False)
        s.flush()
        p = s.get(Patient, row.patient_pk)
        out, pid, room, name, wb = score_out(row), p.patient_id, row.room_code, p.full_name, row.wellbeing
    await manager.broadcast({"type": "psych", "event": "score", "patient_id": pid, "room": room, "score": out})
    return (f"🧠 <b>Bien-être psychologique bas — chambre {esc(room)}</b>\n{esc(name)} : score {wb}/100.\n{esc(out['ai']['explanation'])}\n" + "\n".join(f"• {esc(c)}" for c in out["ai"]["conduct"])
            + f"\n<i>Ce n'est pas un diagnostic. {orchestration.DISCLAIMER}</i>")
