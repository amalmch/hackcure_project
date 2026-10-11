"""
VisionAgent — lisse les états de vision (hystérésis), suit l'état courant du patient et ses transitions :
endormissement, lever nocturne non accompagné, toilettes trop longues, chute, appel, alarme locale ;
enregistre les `MoodObservation` à partir des expressions.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from ..bus import Event, bus
from ..db import session_scope
from ..ingest import handler
from ..models import MoodObservation
from .base import Agent
from .context import is_night

IN_BED = ("lying_bed", "sitting_bed")
OUT_OF_BED = ("sitting_chair", "standing", "walking", "absent")
MOOD_FROM_EXPR = {"pain": "pain", "sad": "sad", "fear": "anxious", "anger": "agitated", "happy": "happy", "surprise": "surprised", "neutral": "calm"}
HYSTERESIS_S = 1.0
TOILET_MAX_S = 15 * 60
OUT_OF_ROOM_MAX_S = 30 * 60


class RoomTrack:
    def __init__(self) -> None:
        self.posture = "lying_bed"
        self.activity = "awake_bed"
        self.candidate: tuple[str, str] | None = None
        self.candidate_since = 0.0
        self.stable_since = time.time()
        self.absent_since: float | None = None
        self.absent_kind: str | None = None
        self.expression = "neutral"
        self.pain_count = 0
        self.persons = 1
        self.reported: dict[str, float] = {}
        self.first_seen = False


class VisionAgent(Agent):
    name = "VisionAgent"
    description = "Lisse les états de la caméra, suit la posture et les transitions (sommeil, lever, toilettes, chute, appel) et note l'humeur."
    patterns = ["hackcure/room/+/vision/#", "hackcure/room/+/call", "hackcure/room/+/safety/alarm", "internal/behavior", "internal/reset"]
    tick_interval = 10.0

    def __init__(self) -> None:
        super().__init__()
        self.rooms: dict[str, RoomTrack] = {}

    def track(self, room: str) -> RoomTrack:
        if room not in self.rooms:
            self.rooms[room] = RoomTrack()
        return self.rooms[room]

    async def candidate(self, room: str, rtype: str, details: dict[str, Any], min_interval: float = 60.0) -> None:
        t = self.track(room)
        now = time.time()
        if now - t.reported.get(rtype, 0) < min_interval:
            return
        t.reported[rtype] = now
        await bus.publish("internal/risk_candidate", {"room": room, "type": rtype, "details": details, "source_agent": self.name})
        await self.insight(room, rtype, details)

    async def insight(self, room: str, rtype: str, details: dict[str, Any]) -> None:
        """Observation comportementale rédigée par le LLM (workflow n8n `vision-watch`), au plus une par chambre toutes les 5 min."""
        t = self.track(room)
        now = time.time()
        if now - t.reported.get("_insight", 0) < 300:
            return
        t.reported["_insight"] = now
        from .. import orchestration
        from .context import is_night
        from .plans import TYPE_LABELS

        rs = handler.room_state(room)
        await orchestration.ask("vision-watch", f"{room}:{int(now)}", {"task": "vision_watch", "chambre": room, "evenement": TYPE_LABELS.get(rtype, rtype), "details": details, "nuit": is_night(),
                                                                         "posture": t.posture, "activite": t.activity, "expression": t.expression, "personnes": t.persons, "confiance": rs.get("confidence"),
                                                                         "source_vision": rs.get("visionSource")}, room=room)

    async def handle(self, ev: Event) -> None:
        if ev.topic == "internal/reset":
            self.rooms.clear()
            return
        p = ev.payload
        if ev.topic == "internal/behavior":
            await self.on_behavior(p)
            return
        room, kind, d = p["room"], p["kind"], p["data"]
        if kind == "vision_state":
            await self.on_state(room, d)
        elif kind == "vision_expression":
            await self.on_expression(room, d)
        elif kind == "vision_staff":
            self.track(room).persons = int(d.get("persons", 1))
        elif kind == "call":
            async with self.working("acting"):
                await self.log(room, input="Bouton d'appel pressé", reasoning="Un appel patient est toujours transmis en priorité au RiskAgent.", output="risque candidat « Appel du patient »")
                await self.candidate(room, "call", {"pressed": True}, min_interval=30)
        elif kind == "safety_alarm":
            async with self.working("acting"):
                reason = d.get("reason")
                await self.log(room, input=f"Alarme locale edge : {reason} (actions locales : {', '.join(d.get('localActionTaken', []) or ['aucune'])})",
                               reasoning="L'edge a déjà appliqué ses règles locales (buzzer/veilleuse) ; on crée le risque côté serveur sans attendre la vision.",
                               output=f"risque candidat « {reason} »")
                if reason == "fall":
                    await self.candidate(room, "fall", {"source": "edge-alarm", "localActionTaken": d.get("localActionTaken", [])}, min_interval=20)
                elif reason == "call":
                    await self.candidate(room, "call", {"source": "edge-alarm"}, min_interval=30)
                else:
                    await self.candidate(room, "local_alarm", {"reason": reason, "localActionTaken": d.get("localActionTaken", [])}, min_interval=30)

    async def on_behavior(self, p: dict[str, Any]) -> None:
        """Risque comportemental du pipeline IA (`behavioral_risk`) : transmis au RiskAgent à partir de « moderate »."""
        room, level = p["room"], p.get("risk_level", "none")
        if p.get("event_type") == "recover" or level in ("none", "low"):
            await bus.publish("internal/risk_clear", {"room": room, "types": ["behavioral_risk"], "reason": "comportement revenu à la normale"})
            return
        indicators = p.get("indicators") or []
        async with self.working("acting"):
            await self.log(room, input=f"risque comportemental {level} (score {float(p.get('risk_score') or 0):.2f}) : {', '.join(indicators) or 'sans indicateur'}",
                           reasoning="Signal du pipeline vision (comportement) sans chute ni douleur avérée : transmis au RiskAgent, qui fixe la sévérité.",
                           output="risque candidat « Comportement à risque »")
            await self.candidate(room, "behavioral_risk", {"risk_level": level, "risk_score": p.get("risk_score"), "indicators": indicators, "recommendations": p.get("recommendations") or []}, min_interval=30)

    async def on_state(self, room: str, d: dict[str, Any]) -> None:
        t = self.track(room)
        t.persons = int(d.get("persons", t.persons))
        posture, activity = d["posture"], d["activity"]
        now = time.time()
        if not t.first_seen:
            t.first_seen = True
            t.posture, t.activity = posture, activity
            return
        if (posture, activity) == (t.posture, t.activity):
            t.candidate = None
            return
        # hystérésis : une nouvelle posture doit persister (sauf chute, acceptée immédiatement)
        if posture != "on_floor" and activity != "fall":
            if t.candidate != (posture, activity):
                t.candidate, t.candidate_since = (posture, activity), now
                return
            if now - t.candidate_since < HYSTERESIS_S:
                return
        prev_posture, prev_activity = t.posture, t.activity
        t.posture, t.activity, t.candidate = posture, activity, None
        t.stable_since = now
        await self.transition(room, t, prev_posture, prev_activity, posture, activity, d)

    async def transition(self, room: str, t: RoomTrack, pp: str, pa: str, posture: str, activity: str, d: dict[str, Any]) -> None:
        night = is_night()
        conf = d.get("confidence")
        base_in = f"posture {pp}/{pa} → {posture}/{activity} (confiance {conf}, personnes {t.persons}, {'nuit' if night else 'jour'})"
        if posture == "on_floor" or activity == "fall":
            async with self.working("acting"):
                await self.log(room, input=base_in, reasoning="Classe CV « patient_fallen » confirmée par le détecteur temporel : chute. Priorité absolue, pas d'hystérésis.", output="risque candidat « Chute » (critical)")
                await self.candidate(room, "fall", {"posture": posture, "confidence": conf, "cvClass": d.get("cvClass")}, min_interval=20)
            return
        if activity == "sleeping" and pa != "sleeping":
            await self.log(room, input=base_in, reasoning="Immobile dans le lit : endormissement.", output="état « endormi » ; humeur : calme")
            self.mood(room, "calm", "endormissement observé")
            return
        if pp in IN_BED and posture in OUT_OF_BED:
            t.absent_since = time.time() if posture == "absent" else None
            t.absent_kind = activity if posture == "absent" else None
            if t.persons <= 1:
                if night:
                    async with self.working("acting"):
                        await self.log(room, input=base_in, reasoning="Sortie du lit la nuit sans personnel dans la chambre : lever non accompagné (risque de chute).", output="risque candidat « Lever non accompagné »")
                        await self.candidate(room, "unaccompanied_bed_exit", {"posture": posture, "night": True, "persons": t.persons})
                else:
                    await self.log(room, input=base_in, reasoning="Sortie du lit de jour, sans personnel : surveillance (risque faible, pondéré par le risque de chute du patient).", output="risque candidat « Sortie du lit » (faible)")
                    await self.candidate(room, "bed_exit", {"posture": posture, "night": False, "persons": t.persons}, min_interval=300)
            else:
                await self.log(room, input=base_in, reasoning="Sortie du lit accompagnée par le personnel : pas de risque.", output="aucune action")
            return
        if pp in OUT_OF_BED and posture in IN_BED:
            t.absent_since = None
            await self.log(room, input=base_in, reasoning="Retour dans le lit.", output="état « au lit »")
            await bus.publish("internal/risk_clear", {"room": room, "types": ["unaccompanied_bed_exit", "bed_exit", "toilet_too_long", "patient_out_of_room"], "reason": "retour au lit"})
            return
        if posture == "absent":
            t.absent_since = time.time()
            t.absent_kind = activity
            await self.log(room, input=base_in, reasoning=f"Patient hors du champ : {'toilettes' if activity == 'toilet' else 'hors de la chambre'}. Chronomètre lancé.", output="surveillance de la durée")
            return
        await self.log(room, input=base_in, reasoning="Changement de posture sans risque particulier.", output=f"état « {posture} »")

    async def on_expression(self, room: str, d: dict[str, Any]) -> None:
        t = self.track(room)
        expr, conf = d["expression"], float(d.get("confidence", 0))
        if expr == "pain" and conf >= 0.4:
            t.pain_count += 1
        else:
            t.pain_count = 0
        if expr != t.expression:
            prev = t.expression
            t.expression = expr
            self.mood(room, MOOD_FROM_EXPR.get(expr, "neutral"), f"expression {expr} ({conf:.2f})")
            if expr == "pain" and t.posture not in ("on_floor",):
                async with self.working("acting"):
                    await self.log(room, input=f"expression {prev} → pain (confiance {conf:.2f})", reasoning="Expression de douleur hors contexte de chute : signalée au RiskAgent.", output="risque candidat « Douleur visible »")
                    await self.candidate(room, "pain", {"expression": expr, "confidence": conf}, min_interval=120)
            elif prev == "pain":
                await bus.publish("internal/risk_clear", {"room": room, "types": ["pain"], "reason": "expression apaisée"})

    def mood(self, room: str, mood: str, note: str) -> None:
        try:
            with session_scope() as s:
                from ..risks import patient_context

                ctx = patient_context(s, room)
                s.add(MoodObservation(admission_id=ctx.get("admission_id"), room_code=room, mood=mood, source=self.name, note=note))
        except Exception:
            pass

    async def on_tick(self) -> None:
        now = time.time()
        for room, t in self.rooms.items():
            if t.absent_since is None:
                continue
            dur = now - t.absent_since
            if t.absent_kind == "toilet" and dur > TOILET_MAX_S:
                await self.candidate(room, "toilet_too_long", {"durationMin": round(dur / 60)}, min_interval=600)
            elif t.absent_kind != "toilet" and dur > OUT_OF_ROOM_MAX_S:
                await self.candidate(room, "patient_out_of_room", {"durationMin": round(dur / 60)}, min_interval=900)


from .. import orchestration as _orchestration  # noqa: E402


@_orchestration.handler("vision-watch")
async def _on_vision_note(ref: str, result: dict[str, Any], meta: dict[str, Any]) -> Optional[str]:
    """Note d'observation rangée avec les humeurs observées (lue par le rapport de garde)."""
    room = ref.split(":")[0]
    note = str(result.get("observation") or "").strip()[:500]
    if not note:
        return None
    with session_scope() as s:
        from ..risks import patient_context

        ctx = patient_context(s, room)
        s.add(MoodObservation(admission_id=ctx.get("admission_id"), room_code=room, mood=str(result.get("mood") or "neutral")[:20], source="vision-watch", note=note))
    return None
