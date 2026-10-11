"""
Règles locales de sécurité (fonctionnent SANS réseau) :
- chute ou appel ⇒ buzzer + veilleuse + message `safety/alarm` (mis en file hors ligne, renvoyé à la reconnexion) ;
- sortie du lit la nuit ⇒ veilleuse ;
- climat : > 27 °C clim, < 19 °C chauffage, fenêtre fermée si l'un est actif ;
- surcharge possible par `cmd/*` (une commande manuelle gèle la règle climat 10 min).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger("edge.rules")
Publish = Callable[[str, dict[str, Any]], None]


class LocalRules:
    def __init__(self, actuators, publish: Publish, room: str, cfg: Optional[dict[str, Any]] = None, source: str = "edge"):
        cfg = cfg or {}
        self.act = actuators
        self.publish = publish
        self.room = room
        self.source = source
        self.night_start = int(cfg.get("night_start", 22))
        self.night_end = int(cfg.get("night_end", 6))
        self.hot = float(cfg.get("climate_hot_c", 27.0))
        self.cold = float(cfg.get("climate_cold_c", 19.0))
        self.buzzer_s = float(cfg.get("buzzer_seconds", 20))
        self.manual_until: dict[str, float] = {}
        self.last_alarm: dict[str, float] = {}
        self.night_override: Optional[bool] = None
        self.alarms_raised: list[dict[str, Any]] = []

    # ── contexte ────────────────────────────────────────────────────────────
    def is_night(self, now: Optional[float] = None) -> bool:
        if self.night_override is not None:
            return self.night_override
        h = datetime.fromtimestamp(now or time.time()).hour
        return h >= self.night_start or h < self.night_end

    def _alarm(self, reason: str, actions: list[str], now: float) -> None:
        if now - self.last_alarm.get(reason, 0) < 15:
            return
        self.last_alarm[reason] = now
        payload = {"ts": datetime.fromtimestamp(now, timezone.utc).isoformat(), "source": self.source, "reason": reason, "localActionTaken": actions}
        self.alarms_raised.append(payload)
        self.publish(f"hackcure/room/{self.room}/safety/alarm", payload)

    # ── événements ──────────────────────────────────────────────────────────
    def on_fall(self, now: Optional[float] = None) -> list[str]:
        now = now or time.time()
        self.act.buzzer.beep(self.buzzer_s)
        self.act.nightlight.on()
        actions = ["buzzer", "nightlight"]
        self._alarm("fall", actions, now)
        return actions

    def on_call(self, now: Optional[float] = None) -> list[str]:
        now = now or time.time()
        self.act.buzzer.beep(min(5.0, self.buzzer_s))
        self.act.nightlight.on()
        actions = ["buzzer", "nightlight"]
        self._alarm("call", actions, now)
        return actions

    def on_bed_exit(self, now: Optional[float] = None) -> list[str]:
        now = now or time.time()
        if self.is_night(now) and self.act.nightlight.state != "on" and now >= self.manual_until.get("light", 0):
            self.act.nightlight.on()
            self._alarm("bed_exit_night", ["nightlight"], now)
            return ["nightlight"]
        return []

    def on_back_in_bed(self, now: Optional[float] = None) -> None:
        now = now or time.time()
        if now >= self.manual_until.get("light", 0) and self.act.nightlight.state == "on" and self.is_night(now):
            # la veilleuse reste allumée la nuit ; de jour on l'éteint
            return
        if now >= self.manual_until.get("light", 0):
            self.act.nightlight.off()

    def on_env(self, temp_c: float, now: Optional[float] = None) -> list[str]:
        now = now or time.time()
        if now < self.manual_until.get("climate", 0):
            return []
        done: list[str] = []
        if temp_c > self.hot:
            if self.act.ac.state != "on":
                self.act.ac.on(); done.append("ac:on")
            if self.act.heater.state == "on":
                self.act.heater.off(); done.append("heater:off")
            if self.act.window.state == "open":
                self.act.window.set(False); done.append("window:closed")
        elif temp_c < self.cold:
            if self.act.heater.state != "on":
                self.act.heater.on(); done.append("heater:on")
            if self.act.ac.state == "on":
                self.act.ac.off(); done.append("ac:off")
            if self.act.window.state == "open":
                self.act.window.set(False); done.append("window:closed")
        elif self.cold + 2 <= temp_c <= self.hot - 2:
            if self.act.ac.state == "on":
                self.act.ac.off(); done.append("ac:off")
            if self.act.heater.state == "on":
                self.act.heater.off(); done.append("heater:off")
        return done

    # ── commandes du serveur (surcharge) ────────────────────────────────────
    def on_command(self, equipment: str, action: str, value: Any, requested_by: str, now: Optional[float] = None) -> tuple[bool, str, Optional[str]]:
        """Applique `cmd/{equipment}`. Refuse d'éteindre le buzzer/la veilleuse pendant une alarme chute récente."""
        now = now or time.time()
        if equipment in ("light", "buzzer") and action in ("off", "close") and now - self.last_alarm.get("fall", 0) < 60:
            return False, self.act.states().get(equipment, "on"), "local_rule: alarme chute en cours"
        ok, state = self.act.apply(equipment, action, value)
        if ok:
            key = "climate" if equipment in ("window", "heater", "ac") else equipment
            self.manual_until[key] = now + 600 if requested_by not in ("EnvironmentAgent",) else now + 120
        return ok, state, None if ok else "unknown equipment"
