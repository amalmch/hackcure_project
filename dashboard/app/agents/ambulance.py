"""
AmbulanceAgent (V2, étape 5) — fait avancer les missions d'ambulance.

- trajet simulé (polyligne, vitesse variable) ou position GPS réelle reçue d'un téléphone ;
- ETA recalculée en continu, diffusée à la carte, à la plateforme et à la 3D (« Réservée — arrivée dans X min ») ;
- à l'arrivée (ETA à zéro) : animation d'entrée dans la 3D, puis installation du patient dans la chambre réservée et
  création de l'admission ;
- le workflow n8n `ambulance-dispatch` rédige le briefing et la préparation (matériel, équipe, examens).
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlmodel import select

from .. import ambulance as geo, orchestration
from ..bus import Event
from ..config import settings
from ..db import session_scope
from ..ingest import handler
from ..models import Admission, AmbulanceMission, Patient
from ..notify import notify
from ..ws import manager
from .base import Agent

esc = lambda t: str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
ACTIVE = ("en_route", "arrived")


def aware(d: Optional[datetime]) -> Optional[datetime]:
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


def mission_out(m: AmbulanceMission, with_route: bool = True) -> dict[str, Any]:
    iso = lambda d: aware(d).isoformat() if d else None  # noqa: E731
    now = datetime.now(timezone.utc)
    eta_s = max(0, int((aware(m.eta_at) - now).total_seconds())) if m.eta_at and m.status == "en_route" else 0
    d = {"id": m.id, "ambulance": m.ambulance_code, "status": m.status, "mode": m.mode, "patient_id": m.patient_id, "patient_name": m.patient_name, "age": m.age, "sex": m.sex, "reason": m.reason,
         "emergency_type": m.emergency_type, "emergency_label": geo.EMERGENCY_TYPES.get(m.emergency_type, m.emergency_type), "severity": m.severity, "severity_label": geo.SEVERITY.get(m.severity, ""),
         "vitals": json.loads(m.vitals_json or "{}"), "departed_at": iso(m.departed_at), "eta_at": iso(m.eta_at), "eta_seconds": eta_s, "eta_minutes": round(eta_s / 60, 1), "arrived_at": iso(m.arrived_at),
         "reserved_room": m.reserved_room, "lat": m.lat, "lon": m.lon, "heading": m.heading, "speed_kmh": round(m.speed_kmh, 1), "remaining_m": round(m.remaining_m), "progress": round(m.progress, 3),
         "preparation": json.loads(m.preparation_json or "{}"), "ai": json.loads(m.ai_json) if m.ai_json else None, "track_url": f"/ambulance/track/{m.track_token}", "route_label": m.route_label,
         "admission_id": m.admission_id}
    if with_route:
        d["route"] = json.loads(m.route_json or "[]")
    return d


def set_reservation(room: Optional[str], m: Optional[AmbulanceMission]) -> None:
    """Statut « Réservée — arrivée dans X min » dans `room_state` (plateforme et 3D)."""
    if not room:
        return
    rs = handler.room_state(room)
    if m is None or m.status not in ACTIVE:
        rs["reservation"] = None
    else:
        eta = max(0, int((aware(m.eta_at) - datetime.now(timezone.utc)).total_seconds())) if m.eta_at else 0
        rs["reservation"] = {"mission_id": m.id, "patient_name": m.patient_name, "emergency": geo.EMERGENCY_TYPES.get(m.emergency_type, ""), "eta_seconds": eta, "eta_minutes": max(0, round(eta / 60)),
                             "status": m.status, "label": "Arrivée en cours" if m.status == "arrived" else f"Réservée — arrivée dans {max(1, round(eta / 60))} min"}
    handler._dirty_rooms.add(room)


class AmbulanceAgent(Agent):
    name = "AmbulanceAgent"
    description = "Suit les ambulances (GPS simulé ou réel), recalcule l'heure d'arrivée, réserve la chambre adaptée, prévient l'équipe et installe le patient à l'arrivée."
    patterns = ["internal/reset"]
    tick_interval = 1.0

    def __init__(self) -> None:
        super().__init__()
        self.last_tick = time.time()
        self.last_broadcast: dict[int, float] = {}

    async def handle(self, ev: Event) -> None:
        return

    async def on_tick(self) -> None:
        now_t = time.time()
        dt, self.last_tick = min(5.0, now_t - self.last_tick), now_t
        now = datetime.now(timezone.utc)
        updates: list[dict[str, Any]] = []
        arrived: list[dict[str, Any]] = []
        admit: list[int] = []
        with session_scope() as s:
            for m in s.exec(select(AmbulanceMission).where(AmbulanceMission.status.in_(ACTIVE))).all():
                if m.status == "en_route":
                    if m.mode == "sim":
                        pts = [tuple(p) for p in json.loads(m.route_json)]
                        total = geo.route_length_m(pts)
                        scale = m.time_scale or settings.ambulance_time_scale
                        m.speed_kmh = geo.speed_kmh(m.progress, m.id)
                        done = m.progress * total + m.speed_kmh / 3.6 * dt * scale
                        m.lat, m.lon, m.heading, m.remaining_m = geo.position_at(pts, done)
                        m.progress = min(1.0, done / total) if total else 1.0
                        m.eta_at = now + timedelta(seconds=geo.eta_seconds(m.remaining_m, m.speed_kmh) / scale)
                    else:  # GPS réel : la position vient du téléphone ; on ne fait que tenir l'ETA à jour
                        m.remaining_m = geo.haversine_m((m.lat, m.lon), (geo.CLINIC["lat"], geo.CLINIC["lon"]))
                        m.eta_at = now + timedelta(seconds=geo.eta_seconds(m.remaining_m, m.speed_kmh))
                    if m.remaining_m <= settings.ambulance_arrival_m:
                        m.status, m.arrived_at, m.eta_at, m.remaining_m, m.progress = "arrived", now, now, 0.0, 1.0
                        arrived.append(mission_out(m, False))
                    set_reservation(m.reserved_room, m)
                    if now_t - self.last_broadcast.get(m.id, 0) >= 1.0 or m.status == "arrived":
                        self.last_broadcast[m.id] = now_t
                        updates.append(mission_out(m, False))
                elif m.status == "arrived" and m.arrived_at and (now - aware(m.arrived_at)).total_seconds() >= settings.ambulance_install_s:
                    admit.append(m.id)
        for u in updates:
            await manager.broadcast({"type": "ambulance", "event": "position", "mission": u})
        for a in arrived:
            await manager.broadcast({"type": "ambulance", "event": "arrived", "mission": a, "install_seconds": settings.ambulance_install_s})
            await notify("warning", f"Ambulance arrivée — {a['patient_name']}", f"{a['emergency_label']} ({a['severity_label']}). Transfert vers la chambre {a['reserved_room']} en cours.", room=a["reserved_room"], target_role="nurse", telegram=False)
            await self.log(a["reserved_room"], input=f"ambulance {a['ambulance']} arrivée (mission #{a['id']})", reasoning="ETA à zéro : entrée de l'ambulance, brancard vers la chambre réservée, installation du patient puis création de l'admission.", output=f"transfert vers la chambre {a['reserved_room']}")
        for mid in admit:
            await self.install(mid)

    async def install(self, mission_id: int) -> None:
        """Le patient est installé au lit de la chambre réservée : l'admission est créée."""
        from .. import state
        from ..api.patients import _admit

        with session_scope() as s:
            m = s.get(AmbulanceMission, mission_id)
            if not m or m.status != "arrived":
                return
            p = s.exec(select(Patient).where(Patient.patient_id == m.patient_id)).first()
            room = m.reserved_room
            if not p or not room or s.exec(select(Admission).where(Admission.room_code == room, Admission.discharged_at.is_(None))).first():
                m.status = "cancelled"
                set_reservation(room, None)
                return
            adm = _admit(s, p, room, f"{geo.EMERGENCY_TYPES.get(m.emergency_type, 'Urgence')} — {m.reason} (arrivée en ambulance {m.ambulance_code})", "Dr Nour Khelifi")
            m.status, m.admission_id = "admitted", adm.id
            s.flush()
            out, pid, name, age = mission_out(m, False), p.patient_id, p.display_name, p.age
        state.register_patient(pid, name, age, room)
        rs = handler.room_state(room)
        rs.update(patient_id=pid, posture="lying_bed", activity="awake_bed", zone="bed", persons=1, reservation=None)
        try:
            from ..sim import embedded

            if embedded.engine is not None and room in embedded.engine.rooms:
                embedded.engine.set_occupied(room, True)
        except Exception:
            pass
        handler._dirty_rooms.add(room)
        await manager.broadcast({"type": "ambulance", "event": "admitted", "mission": out})
        await manager.broadcast({"type": "patients_changed", "room": room, "patient_id": pid})
        await notify("info", f"Patient installé — chambre {room}", f"{out['patient_name']} est installé(e) au lit ; admission créée. Constantes à l'arrivée : {out['vitals'] or 'non transmises'}.", room=room, target_role="nurse", telegram=False)
        await self.log(room, input=f"mission #{mission_id} : patient au lit en chambre {room}", reasoning="Admission créée à partir de la fiche d'intervention de l'ambulance ; la chambre n'est plus « réservée ». Le questionnaire d'admission sera proposé par le PsychAgent.",
                       output=f"admission #{out['admission_id']} créée")


async def dispatch(mission_id: int) -> None:
    """Départ de l'ambulance : notifications à l'équipe + briefing rédigé par le LLM (n8n `ambulance-dispatch`)."""
    with session_scope() as s:
        m = s.get(AmbulanceMission, mission_id)
        if not m:
            return
        out = mission_out(m, False)
        p = s.exec(select(Patient).where(Patient.patient_id == m.patient_id)).first()
        ctx = {"task": "ambulance_dispatch", "mission": {k: out[k] for k in ("patient_name", "age", "sex", "reason", "emergency_label", "severity_label", "vitals", "eta_minutes", "reserved_room")},
               "patient_connu": bool(p and p.history), "antecedents": p.history if p else "", "allergies": (p.allergies if p else "") or "non connues", "preparation_standard": out["preparation"]}
    room = out["reserved_room"]
    prep = out["preparation"]
    body = (f"{out['patient_name']} ({out['age'] or '?'} ans) — {out['emergency_label']}, {out['severity_label']}. Motif : {out['reason']}. Arrivée estimée dans {out['eta_minutes']:.0f} min. "
            f"Chambre {room} réservée. Préparer : {'; '.join(prep.get('materiel', [])[:3])}.")
    for role in ("nurse", "duty_doctor"):
        await notify("warning", f"Ambulance en route — chambre {room} réservée", body, room=room, target_role=role, telegram=False)
    await manager.broadcast({"type": "ambulance", "event": "dispatched", "mission": out})
    path = await orchestration.ask("ambulance-dispatch", str(mission_id), ctx, room=room)
    from . import manager as agents

    agent = agents.get("AmbulanceAgent")
    if agent:
        await agent.log(room, input=f"départ de l'ambulance {out['ambulance']} : {out['patient_name']}, {out['emergency_label']} ({out['severity_label']})", reasoning=f"Chambre {room} réservée automatiquement (préférence par type d'urgence parmi les chambres libres). Équipe prévenue avec la préparation standard ; briefing demandé "
                        + ("au workflow n8n ambulance-dispatch." if path == "n8n" else "au LLM local."), output=f"« Réservée — arrivée dans {out['eta_minutes']:.0f} min »")


@orchestration.handler("ambulance-dispatch")
async def on_briefing(ref: str, result: dict[str, Any], meta: dict[str, Any]) -> Optional[str]:
    clean = lambda xs: [str(x)[:200] for x in (xs or [])][:6]  # noqa: E731
    with session_scope() as s:
        m = s.get(AmbulanceMission, int(ref))
        if not m:
            return None
        prep = result.get("preparation") or {}
        ai = {"briefing": str(result.get("briefing") or "")[:1200], "preparation": {"materiel": clean(prep.get("materiel")), "equipe": clean(prep.get("equipe")), "examens": clean(prep.get("examens"))},
              "provider": meta.get("provider") or "anthropic (n8n)", "fallback": bool(meta.get("fallback"))}
        m.ai_json = json.dumps(ai, ensure_ascii=False)
        s.flush()
        out = mission_out(m, False)
    await manager.broadcast({"type": "ambulance", "event": "briefing", "mission": out})
    p = ai["preparation"]
    return (f"🚑 <b>Ambulance en route — chambre {esc(out['reserved_room'])} réservée</b>\n{esc(out['patient_name'])} · {esc(out['emergency_label'])} · {esc(out['severity_label'])}\nArrivée estimée dans <b>{out['eta_minutes']:.0f} min</b>.\n"
            f"{esc(ai['briefing'])}\n<b>Matériel</b> : {esc('; '.join(p['materiel']))}\n<b>Équipe</b> : {esc('; '.join(p['equipe']))}\n<b>Examens</b> : {esc('; '.join(p['examens']))}\n<i>{orchestration.DISCLAIMER}</i>")
