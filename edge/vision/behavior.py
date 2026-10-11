"""
Analyse comportementale optionnelle de l'edge : fenêtre temporelle (immobilité, agitation, instabilité) et, s'ils
sont déjà sur le disque, Vision Transformer d'Amal (`computer_vision/src/behavior.py`). Publiée sur
`hackcure/room/{room}/vision/behavior`. Toute indisponibilité (paquet, poids) désactive l'analyse sans erreur :
le pipeline de posture continue exactement comme avant.
"""

from __future__ import annotations

import logging
import math
import sys
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("edge.behavior")
CV_DIR = Path(__file__).resolve().parents[2] / "computer_vision"


def build_behavior(cfg: dict[str, Any]) -> Any:
    b = cfg.get("behavior", {}) or {}
    if not b.get("enabled", True):
        return None
    try:
        if str(CV_DIR) not in sys.path:
            sys.path.insert(0, str(CV_DIR))
        from src.behavior import BehaviorAnalyzer  # type: ignore

        analyzer = BehaviorAnalyzer(window_size=int(b.get("window", 30)), device=str(cfg.get("models", {}).get("device", "cpu")), use_transformer=bool(b.get("transformer", True)))
        logger.info("Analyse comportementale active (mode %s)", analyzer.mode)
        return analyzer
    except Exception as exc:
        logger.warning("Analyse comportementale indisponible (%s) : pipeline de posture seul", exc)
        return None


class BehaviorPublisher:
    """Échantillonne ~3 fois par seconde et ne publie que sur changement (sinon toutes les `every_s` secondes)."""

    def __init__(self, analyzer: Any, room: str, sample_s: float = 0.33, every_s: float = 15.0):
        self.analyzer, self.room, self.sample_s, self.every_s = analyzer, room, sample_s, every_s
        self.pos: Optional[tuple[float, float]] = None
        self.sampled = 0.0
        self.key: Optional[tuple] = None
        self.published = 0.0

    def step(self, frame: Any, bbox: tuple[float, float, float, float], cls_name: str, conf: float, discomfort: bool, resting: bool, ts: float) -> Optional[dict[str, Any]]:
        """Renvoie la charge utile `vision/behavior` à publier, ou None."""
        if self.analyzer is None or ts - self.sampled < self.sample_s:
            return None
        self.sampled = ts
        h, w = frame.shape[:2]
        c = ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)
        vel = math.hypot(c[0] - self.pos[0], c[1] - self.pos[1]) / max(1.0, math.hypot(w, h)) if self.pos else None
        self.pos = c
        crop = None
        if self.analyzer.transformer is not None:
            x1, y1, x2, y2 = (int(max(0, v)) for v in bbox)
            crop = frame[y1:min(h, y2), x1:min(w, x2)][:, :, ::-1]  # BGR → RGB
        ev = self.analyzer.update(f"room_{self.room}", cls_name, conf, velocity=vel, crop_rgb=crop, discomfort=discomfort, resting=resting)
        level, indicators = ev.get("behavioral_level", "low"), list(ev.get("evidence") or [])
        key = (level, tuple(indicators))
        if key == self.key and ts - self.published < self.every_s:
            return None
        self.key, self.published = key, ts
        return {"riskLevel": level, "riskScore": float(ev.get("behavioral_score", 0.1)), "indicators": indicators,
                "recommendations": list(ev.get("recommendations") or []) if level != "low" else [], "transformer": bool(ev.get("transformer")),
                "fallProbability": ev.get("transformer_fall_probability")}
