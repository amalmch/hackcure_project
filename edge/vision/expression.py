"""
Expression faciale sur le Pi : modèle FER+ ONNX léger (onnxruntime) ; absent ⇒ `neutral`, confidence 0.
Téléchargement : `python edge/download_ferplus.py` (modèle public ONNX Model Zoo, ~35 Mo).
Mapping FER+ → contrat : neutral, happy, surprise, sad, anger, disgust→anger, fear, contempt→neutral ; la douleur
est inférée de (sad | fear | anger) avec une boîte « patient_fallen / possible_discomfort » ou d'un score élevé.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger("edge.expression")
FERPLUS_LABELS = ["neutral", "happy", "surprise", "sad", "anger", "disgust", "fear", "contempt"]
TO_CONTRACT = {"neutral": "neutral", "happy": "happy", "surprise": "surprise", "sad": "sad", "anger": "anger", "disgust": "anger", "fear": "fear", "contempt": "neutral"}
PAIN_LIKE = {"sad", "fear", "anger", "disgust"}


class ExpressionEstimator:
    def __init__(self, model_path: Optional[str], every_s: float = 3.0):
        self.session = None
        self.every_s = every_s
        self.last_t = 0.0
        self.last = ("neutral", 0.0)
        if model_path and Path(model_path).exists():
            try:
                import onnxruntime as ort  # type: ignore

                self.session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
                self.input_name = self.session.get_inputs()[0].name
                logger.info("FER+ ONNX chargé : %s", model_path)
            except Exception as exc:
                logger.warning("FER+ indisponible (%s) → expression neutre", exc)
        else:
            logger.info("Pas de modèle d'expression (%s) → neutral / 0", model_path)

    @property
    def available(self) -> bool:
        return self.session is not None

    def estimate(self, frame: np.ndarray, bbox: tuple[float, float, float, float], discomfort_hint: bool = False, now: Optional[float] = None) -> tuple[str, float]:
        """Renvoie (expression, confidence). Sans modèle : `pain` si indice d'inconfort CV, sinon neutral/0."""
        now = time.time() if now is None else now
        if now - self.last_t < self.every_s:
            return self.last
        self.last_t = now
        if self.session is None:
            self.last = ("pain", 0.5) if discomfort_hint else ("neutral", 0.0)
            return self.last
        try:
            import cv2

            x1, y1, x2, y2 = map(int, bbox)
            h = max(1, y2 - y1)
            face = frame[max(0, y1):y1 + int(h * 0.35), max(0, x1):max(x1 + 1, x2)]  # tiers supérieur de la boîte
            if face.size == 0:
                return self.last
            gray = cv2.cvtColor(face, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, (64, 64)).astype(np.float32)
            inp = gray[None, None, :, :]
            out = self.session.run(None, {self.input_name: inp})[0][0]
            probs = np.exp(out - out.max())
            probs /= probs.sum()
            idx = int(np.argmax(probs))
            label = TO_CONTRACT[FERPLUS_LABELS[idx]]
            conf = float(probs[idx])
            if FERPLUS_LABELS[idx] in PAIN_LIKE and (discomfort_hint or conf > 0.6):
                label = "pain"
            self.last = (label, round(conf, 3))
        except Exception as exc:
            logger.debug("expression: %s", exc)
        return self.last
