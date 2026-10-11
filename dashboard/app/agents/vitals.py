"""
VitalsAgent — seuils par métrique (ajustés au profil patient), tendances sur 10 min, NEWS2 déterministe,
alertes équipement (perfusion < 50 ml, occlusion, réaction transfusionnelle).
"""

from __future__ import annotations

import time
from typing import Any, Optional

from ..bus import Event, bus
from ..clinical.news2 import news2
from ..ingest import handler
from .. import equipment
from .base import Agent

# seuils par défaut : (type_de_risque, condition) — la sévérité fine est calculée par plans.severity_for
DEFAULT_LIMITS = {"hr_high": 112, "hr_low": 48, "spo2_low": 94, "sys_low": 95, "sys_high": 180, "temp_high": 38.0, "temp_low": 35.0, "rr_high": 25}
PERSIST = 3  # lectures consécutives hors limites avant alerte (anti-bruit)
SECONDARY = {"tachycardia", "bradycardia", "hypotension", "hypertension", "tachypnea"}  # la désaturation est toujours un risque à part entière


def limits_for(patient: Optional[dict[str, Any]]) -> dict[str, float]:
    lim = dict(DEFAULT_LIMITS)
    hist = ((patient or {}).get("history") or "").lower()
    lim["copd"] = False
    if "bpco" in hist or "copd" in hist:
        lim["spo2_low"] = 88  # cible SpO2 88–92 % chez le BPCO
        lim["rr_high"] = 28
        lim["copd"] = True
    if "fibrillation" in hist or "afib" in hist:
        lim["hr_high"] = 120
    return lim


class VitalsAgent(Agent):
    name = "VitalsAgent"
    description = "Surveille les constantes des machines : seuils par patient, tendances 10 min, NEWS2, alertes perfusion/transfusion."
    patterns = ["hackcure/room/+/device/+", "internal/machine_error", "internal/reset"]
    tick_interval = 20.0

    def __init__(self) -> None:
        super().__init__()
        self.reported: dict[tuple[str, str], float] = {}
        self.active: dict[tuple[str, str], bool] = {}
        self.streak: dict[tuple[str, str], int] = {}
        self.rank: dict[tuple[str, str], int] = {}
        self.limits_cache: dict[str, tuple[float, dict[str, float]]] = {}
        self.last_news2: dict[str, int] = {}
        from ..config import settings

        self.tick_interval = settings.vitals_tick_s

    def limits(self, room: str) -> dict[str, float]:
        cached = self.limits_cache.get(room)
        if cached and time.time() - cached[0] < 300:
            return cached[1]
        try:
            from ..db import session_scope
            from ..risks import patient_context

            with session_scope() as s:
                ctx = patient_context(s, room)
            lim = limits_for(ctx.get("patient"))
            known = ctx.get("patient") is not None
        except Exception:
            lim, known = {**DEFAULT_LIMITS, "copd": False}, False
        # patient pas encore lisible (démarrage, base occupée) : nouvelle lecture 10 s plus tard, pas 5 min de seuils par défaut
        self.limits_cache[room] = (time.time() if known else time.time() - 290, lim)
        return lim

    async def raise_candidate(self, room: str, rtype: str, details: dict[str, Any], reasoning: str, min_interval: float = 120.0, rank: int = 0) -> None:
        """`rank` : gravité du signal (0 si non gradué) ; une aggravation est transmise sans attendre `min_interval`."""
        key = (room, rtype)
        now = time.time()
        self.streak[key] = self.streak.get(key, 0) + 1
        if self.streak[key] < PERSIST:
            return
        self.active[key] = True
        worse = rank > self.rank.get(key, 0)
        if not worse and now - self.reported.get(key, 0) < min_interval:
            return
        self.rank[key] = max(rank, self.rank.get(key, 0))
        if rtype in SECONDARY and handler.room_state(room).get("riskLevel") == "critical":
            # conséquence probable d'un risque critique déjà ouvert (chute...) : noté, pas de doublon de risque
            if now - self.reported.get((room, "_secondary_note"), 0) > 120:
                self.reported[(room, "_secondary_note")] = now
                await self.log(room, input=", ".join(f"{k}={v}" for k, v in details.items()), reasoning=reasoning + " Un risque critique est déjà ouvert dans la chambre : signal rattaché, pas de nouveau risque.", output="noté sur le risque critique")
            return
        self.reported[key] = now
        async with self.working("acting"):
            await self.log(room, input=", ".join(f"{k}={v}" for k, v in details.items()), reasoning=reasoning, output=f"risque candidat « {rtype} »")
            await bus.publish("internal/risk_candidate", {"room": room, "type": rtype, "details": details, "source_agent": self.name})
        await self.insight(room, rtype, details)

    async def insight(self, room: str, rtype: str, details: dict[str, Any]) -> None:
        """Lecture de la tendance des constantes par le LLM (workflow n8n `vitals-trend`), au plus une par chambre toutes les 5 min."""
        now = time.time()
        if now - self.reported.get((room, "_insight"), 0) < 300:
            return
        self.reported[(room, "_insight")] = now
        from .. import orchestration
        from .context import current_news2, room_vitals
        from .plans import TYPE_LABELS

        n2 = current_news2(room)
        trend = {name: self.delta(f"{room}-{dev}", metric, 600) for name, dev, metric in (("FC", "ecg", "hr"), ("PAS", "bp", "sys"), ("SpO2", "spo2", "spo2"), ("temperature", "thermometer", "tempC"), ("FR", "ecg", "rr"))}
        await orchestration.ask("vitals-trend", f"{room}:{int(now)}", {"task": "vitals_trend", "chambre": room, "alerte": TYPE_LABELS.get(rtype, rtype), "details": details, "constantes": room_vitals(room),
                                                                         "variation_sur_10_min": {k: round(v, 1) for k, v in trend.items() if v is not None}, "news2": n2.to_dict() if n2 else None,
                                                                         "seuils_du_patient": {k: v for k, v in self.limits(room).items() if k != "copd"}, "bpco": bool(self.limits(room).get("copd"))}, room=room)

    async def clear(self, room: str, rtype: str, reason: str) -> None:
        key = (room, rtype)
        self.streak[key] = 0
        self.rank.pop(key, None)
        if self.active.get(key):
            self.active[key] = False
            await bus.publish("internal/risk_clear", {"room": room, "types": [rtype], "reason": reason})

    async def handle(self, ev: Event) -> None:
        if ev.topic == "internal/reset":
            self.reported.clear()
            self.active.clear()
            self.streak.clear()
            self.rank.clear()
            return
        p = ev.payload
        if ev.topic == "internal/machine_error":
            await self.on_machine_event(p)
            return
        room, d = p["room"], p["data"]
        t, m = d["type"], d.get("metrics", {})
        if equipment.is_fault(t, d.get("fault")):
            if equipment.register(room, t, str(d["fault"]["code"]), str(d["fault"].get("label") or ""), "device"):
                await self.equipment_changed(room)
        elif equipment.clear(room, t, source="device"):
            await self.equipment_changed(room)
        lim = self.limits(room)
        if t == "ecg" and m.get("hr") is not None:
            hr = float(m["hr"])
            if hr > lim["hr_high"]:
                await self.raise_candidate(room, "tachycardia", {"hr": hr, "rhythm": m.get("rhythm"), "limit": lim["hr_high"]}, f"FC {hr:.0f} bpm > seuil patient {lim['hr_high']} bpm (rythme {m.get('rhythm')}).")
            elif hr < lim["hr_low"]:
                await self.raise_candidate(room, "bradycardia", {"hr": hr, "limit": lim["hr_low"]}, f"FC {hr:.0f} bpm < seuil {lim['hr_low']} bpm.")
            else:
                await self.clear(room, "tachycardia", f"FC {hr:.0f} bpm normalisée")
                await self.clear(room, "bradycardia", f"FC {hr:.0f} bpm normalisée")
            if m.get("rr") is not None and float(m["rr"]) >= lim["rr_high"]:
                await self.raise_candidate(room, "tachypnea", {"rr": m["rr"], "limit": lim["rr_high"]}, f"FR {m['rr']}/min ≥ {lim['rr_high']}.")
        elif t == "spo2" and m.get("spo2") is not None:
            s = float(m["spo2"])
            from ..clinical.spo2 import classify

            hist = handler.device_history(f"{room}-spo2", "spo2", 60)
            drop = (max(v for _, v in hist) - s) if len(hist) >= 5 else None
            c = classify(s, copd=bool(lim.get("copd")), drop_per_min=drop)
            if c["level"] != "none":
                await self.raise_candidate(room, "hypoxemia", {"spo2": s, "level": c["level"], "target": c["target"], "dropPerMin": round(drop, 1) if drop is not None else None, "copd": c["copd"], "limit": lim["spo2_low"]},
                                           f"{c['reason']}. Niveau déterministe : {c['level']}.", rank={"attention": 1, "high": 2, "critical": 3}[c["level"]])
            else:
                await self.clear(room, "hypoxemia", f"SpO2 {s:.0f} % normalisée")
        elif t == "bp" and m.get("sys") is not None:
            sy = float(m["sys"])
            if sy < lim["sys_low"]:
                await self.raise_candidate(room, "hypotension", {"sys": sy, "dia": m.get("dia"), "map": m.get("map"), "limit": lim["sys_low"]}, f"PAS {sy:.0f} mmHg < {lim['sys_low']} (PAM {m.get('map')}).")
            elif sy > lim["sys_high"]:
                await self.raise_candidate(room, "hypertension", {"sys": sy, "dia": m.get("dia"), "limit": lim["sys_high"]}, f"PAS {sy:.0f} mmHg > {lim['sys_high']}.")
            else:
                await self.clear(room, "hypotension", f"PAS {sy:.0f} mmHg normalisée")
                await self.clear(room, "hypertension", f"PAS {sy:.0f} mmHg normalisée")
        elif t == "thermometer" and m.get("tempC") is not None:
            tc = float(m["tempC"])
            # la fièvre est qualifiée par le FeverAgent (fièvre vraie ≠ simple hausse thermique)
            if tc <= lim["temp_low"]:
                await self.raise_candidate(room, "hypothermia", {"tempC": tc}, f"Température {tc:.1f} °C ≤ {lim['temp_low']} °C.")
            else:
                await self.clear(room, "hypothermia", f"température {tc:.1f} °C normalisée")
        elif t == "iv_pump":
            vol, occ = m.get("volumeLeftMl"), bool(m.get("occlusion"))
            if occ:
                await self.raise_candidate(room, "iv_occlusion", {"occlusion": True, "volumeLeftMl": vol}, "La pompe signale une occlusion de ligne.", min_interval=300)
            else:
                await self.clear(room, "iv_occlusion", "occlusion levée")
            if vol is not None and float(vol) < 50:
                await self.raise_candidate(room, "iv_empty", {"volumeLeftMl": vol, "rateMlH": m.get("rateMlH")}, f"Volume restant {vol} ml < 50 ml à {m.get('rateMlH')} ml/h.", min_interval=600)
            elif vol is not None and float(vol) > 100:
                await self.clear(room, "iv_empty", f"poche remplacée ({vol} ml)")
        elif t == "transfusion":
            if m.get("reaction"):
                await self.raise_candidate(room, "transfusion_reaction", {"reaction": True, "volumeLeftMl": m.get("volumeLeftMl")}, "Réaction transfusionnelle signalée par l'appareil : arrêt immédiat requis.", min_interval=300)
            else:
                await self.clear(room, "transfusion_reaction", "pas de réaction")

    # ── pannes d'équipement (machine_error) ─────────────────────────────────
    async def on_machine_event(self, p: dict[str, Any]) -> None:
        """Événement `machine_error` / `recover` du pipeline d'Amal : rattaché à notre appareil de la chambre."""
        room = str(p["room"])
        if p.get("active"):
            label = str(p.get("machine_type") or "")
            changed = equipment.register(room, equipment.device_type(label), "reported", f"panne signalée ({label})" if label else "", "legacy")
        else:
            changed = equipment.clear(room, source="legacy")
        if changed:
            await self.equipment_changed(room)

    async def equipment_changed(self, room: str) -> None:
        """Un seul risque « equipment_fault » par chambre, qui liste les appareils en panne ; reflété dans la 3D."""
        from .. import state

        f = equipment.faults(room)
        await state.machine_fault(room, equipment.describe(f) if f else None)
        async with self.working("acting"):
            if f:
                details = {"summary": equipment.describe(f), "severity": equipment.severity(f),
                           "devices": [{"device": v["device"], "type": k, "name": v["name"], "fault": v["label"], "code": v["code"], "source": v["source"]} for k, v in f.items()]}
                await self.log(room, input=f"panne d'équipement : {details['summary']}",
                               reasoning="Appareil signalé en panne (flux de l'appareil ou pipeline de vision). Ce n'est ni une occlusion ni une poche vide (risques de perfusion distincts). "
                                         + ("Appareil vital : sévérité élevée." if details["severity"] == "high" else "Appareil non vital : sévérité moyenne."),
                               output="risque candidat « equipment_fault » ; appareil de remplacement en salle Équipements (étage 1)")
                await bus.publish("internal/risk_candidate", {"room": room, "type": "equipment_fault", "details": details, "source_agent": self.name})
            else:
                await self.log(room, input="appareils de nouveau en service", reasoning="Plus aucune panne signalée dans la chambre.", output="signal levé — à confirmer par un soignant")
                await bus.publish("internal/risk_clear", {"room": room, "types": ["equipment_fault"], "reason": "appareils de nouveau en service"})

    async def on_tick(self) -> None:
        """NEWS2 et tendances 10 min pour chaque chambre."""
        for room in handler.ROOMS:
            v = handler.room_state(room).get("vitals") or {}
            if v.get("hr") is None or v.get("spo2") is None:
                continue
            res = news2(rr=v.get("rr"), spo2=v.get("spo2"), on_oxygen=bool((v.get("o2FlowLMin") or 0) > 0), sbp=v.get("sys"), hr=v.get("hr"), temp=v.get("tempC"), spo2_scale2=bool(self.limits(room).get("copd")))
            handler.room_state(room)["news2"] = res.to_dict()
            if res.score >= 5:
                await self.raise_candidate(room, "news2_high", {"news2": res.score, "components": res.components, **{k: v.get(k) for k in ("hr", "spo2", "sys", "tempC", "rr")}},
                                           f"NEWS2 = {res.score} ({res.band}) : composantes {res.components}.", min_interval=300)
            elif res.score <= 2:
                await self.clear(room, "news2_high", f"NEWS2 {res.score}")
            self.last_news2[room] = res.score
            # tendance sepsis : +1 °C et +20 bpm sur 10 min, ou PAS en baisse de 20 mmHg avec FC en hausse
            d_temp = self.delta(f"{room}-thermometer", "tempC", 600)
            d_hr = self.delta(f"{room}-ecg", "hr", 600)
            d_sys = self.delta(f"{room}-bp", "sys", 600)
            if (d_temp is not None and d_hr is not None and d_temp >= 0.8 and d_hr >= 18) or (d_sys is not None and d_hr is not None and d_sys <= -18 and d_hr >= 18):
                await self.raise_candidate(room, "sepsis_trend", {"deltaTemp10min": round(d_temp or 0, 1), "deltaHr10min": round(d_hr or 0), "deltaSys10min": round(d_sys or 0), "news2": res.score, "tempC": v.get("tempC"), "hr": v.get("hr"), "sys": v.get("sys")},
                                           f"Tendance 10 min : T° {d_temp:+.1f} °C, FC {d_hr:+.0f} bpm, PAS {d_sys or 0:+.0f} mmHg → profil évocateur de sepsis (NEWS2 {res.score}).", min_interval=600)

    @staticmethod
    def delta(device_id: str, metric: str, seconds: int) -> Optional[float]:
        pts = handler.device_history(device_id, metric, seconds)
        if len(pts) < 10:
            return None
        head = [v for _, v in pts[:5]]
        tail = [v for _, v in pts[-5:]]
        return sum(tail) / len(tail) - sum(head) / len(head)


from .. import orchestration as _orchestration  # noqa: E402


@_orchestration.handler("vitals-trend")
async def _on_vitals_note(ref: str, result: dict[str, Any], meta: dict[str, Any]) -> Optional[str]:
    """Lecture de tendance affichée avec les constantes de la chambre (`room_state.vitalsNote`)."""
    room = ref.split(":")[0]
    rs = handler.room_state(room)
    rs["vitalsNote"] = {"text": str(result.get("reading") or "")[:500], "watch": [str(x)[:160] for x in (result.get("watch") or [])][:4], "provider": meta.get("provider") or "anthropic (n8n)", "ts": time.time()}
    handler._dirty_rooms.add(room)
    return None
