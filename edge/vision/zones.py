"""Zones de la chambre (polygones normalisés) avec hystérésis temporelle."""

from __future__ import annotations

import time
from typing import Iterable, Optional

Point = tuple[float, float]
Polygon = list[Point]


def point_in_polygon(pt: Point, poly: Iterable[Point]) -> bool:
    """Ray casting classique (polygone simple, coordonnées normalisées)."""
    poly = list(poly)
    if len(poly) < 3:
        return False
    x, y = pt
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            x_int = (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi
            if x < x_int:
                inside = not inside
        j = i
    return inside


class ZoneTracker:
    """
    Classe un point (bas-centre de la boîte ou hanches) en `bed | bathroom_door | exit | floor`,
    avec hystérésis : une nouvelle zone n'est acceptée qu'après `hysteresis_s` secondes de persistance.
    """

    ORDER = ("bed", "bathroom_door", "exit")

    def __init__(self, zones: dict[str, Polygon], hysteresis_s: float = 2.0):
        self.zones = {k: [tuple(p) for p in v] for k, v in zones.items() if isinstance(v, list)}
        self.hysteresis_s = hysteresis_s
        self.current: str = "none"
        self.candidate: Optional[str] = None
        self.candidate_since: float = 0.0
        self.last_known: str = "none"

    def raw_zone(self, pt: Optional[Point]) -> str:
        if pt is None:
            return "none"
        for name in self.ORDER:
            poly = self.zones.get(name)
            if poly and point_in_polygon(pt, poly):
                return name
        return "floor"

    def update(self, pt: Optional[Point], now: Optional[float] = None) -> str:
        now = time.time() if now is None else now
        raw = self.raw_zone(pt)
        if raw == self.current:
            self.candidate = None
            return self.current
        if self.current == "none" and raw != "none":
            self.current, self.candidate = raw, None   # premiere zone connue : acceptee immediatement
            return self.current
        if self.candidate != raw:
            self.candidate, self.candidate_since = raw, now
            return self.current
        if now - self.candidate_since >= self.hysteresis_s or self.current == "none":
            if self.current != "none":
                self.last_known = self.current
            self.current = raw
            self.candidate = None
        return self.current

    def reset(self) -> None:
        self.current, self.candidate, self.last_known = "none", None, "none"
