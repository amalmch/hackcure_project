"""
Pipeline vision de l'edge avec repli automatique (section 6.4) :
1. poids entraînés `runs/detect/**/weights/best.pt` → `PatientMonitor` de `computer_vision/src`
   (classes canoniques) ou modèle 2 classes (`falling` / `no_falling`) ;
2. modèle pose pré-entraîné (`yolo11n-pose.pt` / `yolov8n-pose.pt`, téléchargé par Ultralytics) + posture par règles ;
3. générateur d'états synthétiques (`--fake`).
Le nom du mode actif est publié dans `source` : `edge-yolo`, `edge-2cls`, `edge-pose`, `edge-fake`.
"""

from __future__ import annotations

import glob
import logging
import math
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np

from .persons import Track
from .posture_map import pose_rule_posture

logger = logging.getLogger("edge.vision")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CV_DIR = PROJECT_ROOT / "computer_vision"
CANONICAL = {"patient_fallen", "patient_lying", "patient_moving_out", "patient_near_fall", "patient_out", "patient_sitting", "possible_discomfort"}
COCO_KP = ["nose", "left_eye", "right_eye", "left_ear", "right_ear", "left_shoulder", "right_shoulder", "left_elbow", "right_elbow", "left_wrist", "right_wrist", "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle"]


@dataclass
class FrameResult:
    tracks: list[Track]
    mode: str
    fall_confirmed: dict[int, bool] = field(default_factory=dict)
    discomfort: dict[int, bool] = field(default_factory=dict)
    width: int = 640
    height: int = 480


def find_weights(patterns: list[str]) -> Optional[Path]:
    for pat in patterns:
        for p in sorted(glob.glob(str(PROJECT_ROOT / pat), recursive=True), key=lambda x: Path(x).stat().st_mtime, reverse=True):
            return Path(p)
    return None


class BasePipeline:
    mode = "edge-fake"

    def process(self, frame: np.ndarray, ts: float) -> FrameResult:  # pragma: no cover - interface
        raise NotImplementedError


class CanonicalPipeline(BasePipeline):
    """Réutilise `computer_vision/src` (PatientMonitor : YOLO + ByteTrack + FallDetector + inconfort)."""

    mode = "edge-yolo"

    def __init__(self, weights: Path, confidence: float, imgsz: int, device: str, temporal_config: Optional[Path]):
        if str(CV_DIR) not in sys.path:
            sys.path.insert(0, str(CV_DIR))
        from src.inference import PatientMonitor  # type: ignore

        self.monitor = PatientMonitor(model_path=weights, confidence=confidence, imgsz=imgsz, device=device, temporal_config=temporal_config if temporal_config and temporal_config.exists() else None)
        logger.info("Pipeline canonique : %s (%s)", weights, list(self.monitor.class_names.values()) if hasattr(self.monitor.class_names, "values") else self.monitor.class_names)

    def process(self, frame: np.ndarray, ts: float) -> FrameResult:
        h, w = frame.shape[:2]
        outputs = self.monitor.process_frame(frame, ts)
        tracks, falls, disc = [], {}, {}
        for o in outputs:
            tid = int(o["patient_id"])
            x1, y1, x2, y2 = o["bbox"]
            tracks.append(Track(track_id=tid, bbox=(x1, y1, x2, y2), cls=o["state"], conf=float(o["confidence"])))
            falls[tid] = bool(o.get("fall_event", {}).get("detected"))
            disc[tid] = bool(o.get("possible_discomfort", {}).get("detected"))
        return FrameResult(tracks, self.mode, falls, disc, w, h)


class TwoClassPipeline(BasePipeline):
    """Modèle 2 classes du dépôt (`train_yolo.py`) : `falling` / `no_falling`, suivi ByteTrack d'Ultralytics."""

    mode = "edge-2cls"

    def __init__(self, weights: Path, confidence: float, imgsz: int, device: str):
        from ultralytics import YOLO  # type: ignore

        self.model = YOLO(str(weights))
        self.confidence, self.imgsz, self.device = confidence, imgsz, device
        self.fall_streak: dict[int, int] = {}

    def process(self, frame: np.ndarray, ts: float) -> FrameResult:
        h, w = frame.shape[:2]
        res = self.model.track(frame, conf=self.confidence, imgsz=self.imgsz, device=self.device, persist=True, verbose=False, tracker="bytetrack.yaml")
        tracks, falls = [], {}
        if res and res[0].boxes is not None:
            b = res[0].boxes
            ids = b.id.int().tolist() if b.id is not None else list(range(len(b)))
            for i, box in enumerate(b):
                tid = int(ids[i])
                name = self.model.names[int(box.cls[0])]
                x1, y1, x2, y2 = map(float, box.xyxy[0])
                tracks.append(Track(track_id=tid, bbox=(x1, y1, x2, y2), cls=name, conf=float(box.conf[0])))
                self.fall_streak[tid] = self.fall_streak.get(tid, 0) + 1 if name == "falling" else 0
                falls[tid] = self.fall_streak[tid] >= 3
        return FrameResult(tracks, self.mode, falls, {}, w, h)


class PosePipeline(BasePipeline):
    """Modèle pose pré-entraîné + règles (angle du torse, hauteur des hanches)."""

    mode = "edge-pose"

    def __init__(self, names: list[str], confidence: float, imgsz: int, device: str):
        from ultralytics import YOLO  # type: ignore

        last_err: Optional[Exception] = None
        for n in names:
            try:
                self.model = YOLO(n)
                logger.info("Pipeline pose : %s", n)
                break
            except Exception as exc:  # pragma: no cover - réseau
                last_err = exc
        else:
            raise RuntimeError(f"Aucun modèle pose disponible : {last_err}")
        self.confidence, self.imgsz, self.device = confidence, imgsz, device
        self.lying_streak: dict[int, int] = {}
        self.prev_center: dict[int, tuple[float, float, float]] = {}

    def process(self, frame: np.ndarray, ts: float) -> FrameResult:
        h, w = frame.shape[:2]
        res = self.model.track(frame, conf=self.confidence, imgsz=self.imgsz, device=self.device, persist=True, verbose=False)
        tracks, falls = [], {}
        if res and res[0].boxes is not None:
            b = res[0].boxes
            kps = res[0].keypoints.xy.tolist() if res[0].keypoints is not None else [None] * len(b)
            ids = b.id.int().tolist() if b.id is not None else list(range(len(b)))
            for i, box in enumerate(b):
                tid = int(ids[i])
                x1, y1, x2, y2 = map(float, box.xyxy[0])
                kp = {COCO_KP[j]: (float(p[0]), float(p[1])) for j, p in enumerate(kps[i] or []) if p and (p[0] > 0 or p[1] > 0)}
                cls = pose_rule_posture(kp, y2 - y1)
                # chute = passage rapide vers « lying » hors du lit, maintenu ≥ 3 images (vérifié par posture_map via la zone)
                self.lying_streak[tid] = self.lying_streak.get(tid, 0) + 1 if cls == "pose_lying" else 0
                prev = self.prev_center.get(tid)
                cy = (y1 + y2) / 2
                rapid_down = bool(prev and ts - prev[2] < 1.5 and (cy - prev[1]) / h > 0.12)
                self.prev_center[tid] = ((x1 + x2) / 2, cy, ts)
                falls[tid] = cls == "pose_lying" and self.lying_streak[tid] >= 3 and (rapid_down or self.lying_streak[tid] >= 8)
                tracks.append(Track(track_id=tid, bbox=(x1, y1, x2, y2), cls=cls, conf=float(box.conf[0]), keypoints=kp))
        return FrameResult(tracks, self.mode, falls, {}, w, h)


class FakePipeline(BasePipeline):
    """Générateur d'états synthétiques (`--fake`) : scénario en boucle lit → assis → debout → marche → chute → retour."""

    mode = "edge-fake"
    SCRIPT = [("patient_lying", 0.40, 0.75, 20), ("patient_sitting", 0.40, 0.70, 8), ("patient_moving_out", 0.72, 0.80, 6), ("patient_moving_out", 0.88, 0.50, 6),
              ("patient_fallen", 0.75, 0.90, 12), ("patient_sitting", 0.40, 0.70, 6), ("patient_lying", 0.40, 0.75, 30)]

    def __init__(self, width: int = 640, height: int = 480, speed: float = 1.0, staff_every_s: float = 90.0):
        self.w, self.h, self.speed = width, height, speed
        self.t0 = time.time()
        self.staff_every = staff_every_s
        self.fall_frames = 0

    def process(self, frame: np.ndarray, ts: float) -> FrameResult:
        elapsed = (ts - self.t0) * self.speed
        total = sum(s[3] for s in self.SCRIPT)
        t = elapsed % total
        acc = 0.0
        cls, cx, cy = self.SCRIPT[0][:3]
        for c, x, y, d in self.SCRIPT:
            if t < acc + d:
                cls, cx, cy = c, x, y
                break
            acc += d
        jitter = lambda a: a + random.gauss(0, 0.004)
        bw, bh = (0.26, 0.18) if cls in ("patient_lying", "patient_fallen") else (0.12, 0.30)
        x1, y1 = (jitter(cx) - bw / 2) * self.w, (jitter(cy) - bh) * self.h
        tracks = [Track(1, (x1, y1, x1 + bw * self.w, y1 + bh * self.h), cls, 0.9 + random.uniform(-0.05, 0.05))]
        self.fall_frames = self.fall_frames + 1 if cls == "patient_fallen" else 0
        falls = {1: self.fall_frames >= 5}
        # un soignant passe périodiquement (après la chute dans le script)
        if cls == "patient_fallen" and self.fall_frames > 8 or (elapsed % self.staff_every) < 12:
            tracks.append(Track(2, (0.62 * self.w, 0.35 * self.h, 0.74 * self.w, 0.85 * self.h), "staff", 0.8))
        return FrameResult(tracks, self.mode, falls, {}, self.w, self.h)


def build_pipeline(cfg: dict[str, Any], fake: bool = False) -> BasePipeline:
    """Choisit le pipeline selon les poids disponibles (ordre de repli 6.4)."""
    m = cfg.get("models", {})
    if fake:
        logger.info("Pipeline synthétique (--fake)")
        return FakePipeline(cfg.get("camera", {}).get("width", 640), cfg.get("camera", {}).get("height", 480))
    conf, imgsz, device = float(m.get("confidence", 0.35)), int(m.get("imgsz", 640)), str(m.get("device", "cpu"))
    weights = find_weights(m.get("weights_search", []))
    if weights:
        try:
            from ultralytics import YOLO  # type: ignore

            names = set(YOLO(str(weights)).names.values())
            if names & CANONICAL:
                return CanonicalPipeline(weights, conf, imgsz, device, PROJECT_ROOT / m.get("temporal_config", "computer_vision/configs/temporal.yaml"))
            if {"falling", "no_falling"} & names:
                return TwoClassPipeline(weights, conf, imgsz, device)
            logger.warning("Poids %s : classes inconnues %s", weights, names)
        except Exception as exc:
            logger.warning("Poids entraînés inutilisables (%s) → modèle pose", exc)
    try:
        return PosePipeline(list(m.get("pose_fallback", ["yolo11n-pose.pt", "yolov8n-pose.pt"])), conf, imgsz, device)
    except Exception as exc:
        logger.warning("Modèle pose indisponible (%s) → générateur synthétique", exc)
    return FakePipeline(cfg.get("camera", {}).get("width", 640), cfg.get("camera", {}).get("height", 480))
