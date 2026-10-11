"""
Capteurs GPIO : DHT22 (température / humidité, GPIO4), bouton d'appel (GPIO22), contact de porte (GPIO5).
Chaque pilote détecte l'absence de matériel / de bibliothèque et passe en simulation.
"""

from __future__ import annotations

import logging
import math
import random
import time
from typing import Callable, Optional

logger = logging.getLogger("edge.sensors")


class DHT22:
    def __init__(self, pin: int = 4):
        self.pin = pin
        self.dev = None
        self.simulated = True
        try:
            import adafruit_dht  # type: ignore
            import board  # type: ignore

            self.dev = adafruit_dht.DHT22(getattr(board, f"D{pin}"))
            self.simulated = False
            logger.info("DHT22 sur GPIO%d", pin)
        except Exception as exc:
            logger.info("DHT22 absent (%s) → simulation", exc.__class__.__name__)
        self._last = (22.5, 45.0)

    def read(self) -> tuple[float, float]:
        if self.dev is not None:
            try:
                t, h = self.dev.temperature, self.dev.humidity
                if t is not None and h is not None:
                    self._last = (float(t), float(h))
            except RuntimeError:  # lecture DHT parfois bruitée
                pass
            return self._last
        now = time.time()
        return round(22.5 + 0.8 * math.sin(now / 600.0) + random.gauss(0, 0.05), 2), round(45 + 3 * math.sin(now / 900.0) + random.gauss(0, 0.3), 1)


class DigitalInput:
    """Entrée tout-ou-rien (bouton d'appel, contact de porte) avec simulation (`simulate_press()`)."""

    def __init__(self, pin: int, name: str, pull_up: bool = True, bounce_s: float = 0.05):
        self.pin, self.name = pin, name
        self.dev = None
        self.simulated = True
        self._sim_state = False
        self._pressed_flag = False
        self.on_press: Optional[Callable[[], None]] = None
        try:
            from gpiozero import Button  # type: ignore

            self.dev = Button(pin, pull_up=pull_up, bounce_time=bounce_s)
            self.dev.when_pressed = self._on_pressed
            self.simulated = False
            logger.info("%s sur GPIO%d", name, pin)
        except Exception as exc:
            logger.info("%s : GPIO indisponible (%s) → simulation", name, exc.__class__.__name__)

    def _on_pressed(self) -> None:
        self._pressed_flag = True
        if self.on_press:
            try:
                self.on_press()
            except Exception:
                logger.exception("on_press")

    @property
    def is_active(self) -> bool:
        if self.dev is not None:
            return bool(self.dev.is_pressed)
        return self._sim_state

    def consume_press(self) -> bool:
        flag = self._pressed_flag
        self._pressed_flag = False
        return flag

    def simulate_press(self) -> None:
        self._sim_state = True
        self._on_pressed()
        self._sim_state = False

    def simulate_set(self, state: bool) -> None:
        self._sim_state = state
