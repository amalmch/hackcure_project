"""
Actionneurs GPIO : buzzer (GPIO17), veilleuse (GPIO27), LED chauffage (GPIO23), LED clim (GPIO24), servo fenêtre (GPIO18).
Sans matériel : simulation (état mémorisé, journalisé).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

logger = logging.getLogger("edge.actuators")


class OnOff:
    def __init__(self, pin: int, name: str):
        self.pin, self.name = pin, name
        self.state = "off"
        self.dev = None
        self.simulated = True
        try:
            from gpiozero import OutputDevice  # type: ignore

            self.dev = OutputDevice(pin, initial_value=False)
            self.simulated = False
        except Exception:
            pass

    def set(self, on: bool) -> str:
        self.state = "on" if on else "off"
        if self.dev is not None:
            try:
                self.dev.on() if on else self.dev.off()
            except Exception as exc:  # pragma: no cover
                logger.warning("%s: %s", self.name, exc)
        logger.info("%s → %s%s", self.name, self.state, " (sim)" if self.simulated else "")
        return self.state

    def on(self) -> str:
        return self.set(True)

    def off(self) -> str:
        return self.set(False)


class Buzzer(OnOff):
    def beep(self, seconds: float) -> None:
        self.on()

        def _off():
            time.sleep(seconds)
            self.off()

        threading.Thread(target=_off, daemon=True).start()


class WindowServo:
    """Servo de fenêtre : 0° fermé, 90° ouvert."""

    def __init__(self, pin: int = 18):
        self.pin = pin
        self.state = "closed"
        self.dev = None
        self.simulated = True
        try:
            from gpiozero import AngularServo  # type: ignore

            self.dev = AngularServo(pin, min_angle=0, max_angle=90, initial_angle=0)
            self.simulated = False
        except Exception:
            pass

    def set(self, open_: bool) -> str:
        self.state = "open" if open_ else "closed"
        if self.dev is not None:
            try:
                self.dev.angle = 90 if open_ else 0
            except Exception as exc:  # pragma: no cover
                logger.warning("servo: %s", exc)
        logger.info("fenêtre → %s%s", self.state, " (sim)" if self.simulated else "")
        return self.state


class Actuators:
    def __init__(self, cfg: dict):
        self.buzzer = Buzzer(cfg.get("buzzer_pin", 17), "buzzer")
        self.nightlight = OnOff(cfg.get("nightlight_pin", 27), "veilleuse")
        self.heater = OnOff(cfg.get("heater_led_pin", 23), "LED chauffage")
        self.ac = OnOff(cfg.get("ac_led_pin", 24), "LED clim")
        self.window = WindowServo(cfg.get("window_servo_pin", 18))

    def apply(self, equipment: str, action: str, value=None) -> tuple[bool, str]:
        if equipment == "window":
            return True, self.window.set(action in ("open", "on"))
        if equipment == "heater":
            return True, self.heater.set(action in ("on", "open"))
        if equipment == "ac":
            return True, self.ac.set(action in ("on", "open"))
        if equipment == "light":
            return True, self.nightlight.set(action in ("on", "open"))
        if equipment == "buzzer":
            if action in ("on", "open"):
                self.buzzer.beep(float(value) if value else 3.0)
                return True, "on"
            return True, self.buzzer.off()
        return False, "unknown"

    def states(self) -> dict[str, str]:
        return {"window": self.window.state, "heater": self.heater.state, "ac": self.ac.state, "light": self.nightlight.state}
