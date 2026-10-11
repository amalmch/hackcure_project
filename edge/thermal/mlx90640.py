"""
Caméra thermique MLX90640 (I²C, 32×24, 4 Hz) : température max dans la zone de la tête
(tiers supérieur de la boîte patient projetée), offset de calibration.
`calibrated=false` tant qu'aucune calibration n'est enregistrée. Capteur absent ⇒ valeur simulée, `source: "sim"`.
"""

from __future__ import annotations

import json
import logging
import math
import random
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("edge.thermal")


class ThermalCamera:
    W, H = 32, 24

    def __init__(self, enabled: bool = True, i2c_address: int = 0x33, refresh_hz: int = 4, calibration_offset_c: float = 0.0, calibration_file: Optional[str] = None):
        self.enabled = enabled
        self.offset = float(calibration_offset_c)
        self.calibration_file = Path(calibration_file) if calibration_file else None
        self.calibrated = self.offset != 0.0
        if self.calibration_file and self.calibration_file.exists():
            try:
                data = json.loads(self.calibration_file.read_text(encoding="utf-8"))
                self.offset = float(data.get("offset_c", self.offset))
                self.calibrated = True
            except Exception:
                pass
        self.sensor = None
        self.simulated = True
        self._sim_base = 36.4
        if enabled:
            try:
                import adafruit_mlx90640  # type: ignore
                import board  # type: ignore
                import busio  # type: ignore

                i2c = busio.I2C(board.SCL, board.SDA, frequency=800000)
                self.sensor = adafruit_mlx90640.MLX90640(i2c, address=i2c_address)
                rate = {1: adafruit_mlx90640.RefreshRate.REFRESH_1_HZ, 2: adafruit_mlx90640.RefreshRate.REFRESH_2_HZ, 4: adafruit_mlx90640.RefreshRate.REFRESH_4_HZ, 8: adafruit_mlx90640.RefreshRate.REFRESH_8_HZ}
                self.sensor.refresh_rate = rate.get(refresh_hz, adafruit_mlx90640.RefreshRate.REFRESH_4_HZ)
                self.simulated = False
                logger.info("MLX90640 détecté (0x%02x, %d Hz)", i2c_address, refresh_hz)
            except Exception as exc:
                logger.info("MLX90640 absent (%s) → simulation", exc.__class__.__name__)
        self.frame = [0.0] * (self.W * self.H)

    @property
    def source(self) -> str:
        return "edge-thermal" if not self.simulated else "sim"

    def read_frame(self) -> list[float]:
        if self.sensor is not None:
            try:
                self.sensor.getFrame(self.frame)
                return self.frame
            except Exception as exc:  # pragma: no cover - matériel
                logger.debug("getFrame: %s", exc)
        # simulation : fond 22 °C, tête chaude ~36.5 °C au centre haut
        t = time.time()
        base = self._sim_base + 0.15 * math.sin(t / 40.0)
        for y in range(self.H):
            for x in range(self.W):
                d = math.hypot(x - 16, y - 6)
                self.frame[y * self.W + x] = (base - d * 0.6 if d < 6 else 22.0) + random.gauss(0, 0.08)
        return self.frame

    def head_temperature(self, bbox_norm: Optional[tuple[float, float, float, float]] = None) -> tuple[float, float]:
        """(skinTempC estimée, maxTempC) — max dans la zone tête (tiers supérieur de la boîte patient projetée) ou de l'image."""
        frame = self.read_frame()
        if bbox_norm:
            x1, y1, x2, y2 = bbox_norm
            xs = range(max(0, int(x1 * self.W)), min(self.W, max(1, int(x2 * self.W))))
            ys = range(max(0, int(y1 * self.H)), min(self.H, max(1, int((y1 + (y2 - y1) / 3) * self.H))))
            vals = [frame[y * self.W + x] for y in ys for x in xs] or frame
        else:
            vals = frame
        mx = max(vals)
        skin = mx + self.offset
        return round(skin, 2), round(max(frame), 2)

    def calibrate(self, reference_c: float, bbox_norm: Optional[tuple[float, float, float, float]] = None) -> float:
        """Enregistre l'offset = référence (thermomètre) − mesure courante."""
        measured, _ = self.head_temperature(bbox_norm)
        self.offset = round(reference_c - (measured - self.offset), 2)
        self.calibrated = True
        if self.calibration_file:
            self.calibration_file.parent.mkdir(parents=True, exist_ok=True)
            self.calibration_file.write_text(json.dumps({"offset_c": self.offset, "reference_c": reference_c, "at": time.time()}), encoding="utf-8")
        return self.offset

    def set_sim_fever(self, temp_c: float) -> None:
        self._sim_base = temp_c
