"""
Patient Tracker
===============
Wraps YOLOv8 + ByteTrack for persistent patient tracking across frames.
Maintains track histories for temporal analysis.
"""

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from ultralytics import YOLO

logger = logging.getLogger(__name__)


@dataclass
class TrackState:
    """State of a single tracked patient."""

    track_id: int
    bbox: list[float] = field(default_factory=list)  # [x1, y1, x2, y2]
    center: tuple[float, float] = (0.0, 0.0)
    bottom_center: tuple[float, float] = (0.0, 0.0)
    class_id: int = -1
    class_name: str = ""
    confidence: float = 0.0
    frame_idx: int = 0
    timestamp: float = 0.0
    image_width: int = 0
    image_height: int = 0

    # History (populated by tracker)
    center_history: deque = field(
        default_factory=lambda: deque(maxlen=60)
    )
    state_history: deque = field(
        default_factory=lambda: deque(maxlen=60)
    )
    confidence_history: deque = field(
        default_factory=lambda: deque(maxlen=60)
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for structured output."""
        return {
            "track_id": self.track_id,
            "bbox": self.bbox,
            "center": list(self.center),
            "bottom_center": list(self.bottom_center),
            "class_id": self.class_id,
            "class_name": self.class_name,
            "confidence": self.confidence,
            "frame_idx": self.frame_idx,
            "timestamp": self.timestamp,
        }


class PatientTracker:
    """
    Patient tracker using YOLOv8 + ByteTrack.

    Maintains persistent track IDs and state histories for each patient.
    """

    def __init__(
        self,
        model_path: str | Path = "yolov8n.pt",
        confidence: float = 0.25,
        iou_threshold: float = 0.45,
        device: str | int = "0",
        imgsz: int = 640,
        tracker_config: str = "bytetrack.yaml",
        history_length: int = 60,
    ):
        """
        Initialize the patient tracker.

        Args:
            model_path: Path to YOLOv8n weights.
            confidence: Minimum detection confidence.
            iou_threshold: NMS IoU threshold.
            device: CUDA device or 'cpu'.
            imgsz: Inference image size.
            tracker_config: ByteTrack config (Ultralytics built-in).
            history_length: Number of frames to retain in history.
        """
        self.model = YOLO(str(model_path))
        self.confidence = confidence
        self.iou_threshold = iou_threshold
        self.device = device
        self.imgsz = imgsz
        self.tracker_config = tracker_config
        self.history_length = history_length

        # Persistent track states
        self.tracks: dict[int, TrackState] = {}
        self.frame_count: int = 0
        self.class_names = self.model.names

    def update(
        self,
        frame: np.ndarray,
        timestamp: float | None = None,
    ) -> list[TrackState]:
        """
        Process a single frame: detect + track.

        Args:
            frame: BGR numpy array.
            timestamp: Optional timestamp in seconds.

        Returns:
            List of TrackState objects for active tracks in this frame.
        """
        self.frame_count += 1
        ts = timestamp if timestamp is not None else self.frame_count / 30.0

        results = self.model.track(
            source=frame,
            conf=self.confidence,
            iou=self.iou_threshold,
            device=self.device,
            imgsz=self.imgsz,
            tracker=self.tracker_config,
            persist=True,
            verbose=False,
        )

        active_tracks = []

        for result in results:
            if result.boxes is None or result.boxes.id is None:
                continue

            img_h, img_w = result.orig_shape

            for i in range(len(result.boxes)):
                box = result.boxes[i]
                track_id = int(box.id[0].cpu().numpy())
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().tolist()
                conf = float(box.conf[0].cpu().numpy())
                cls_id = int(box.cls[0].cpu().numpy())
                cls_name = self.class_names.get(cls_id, f"class_{cls_id}")

                center = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
                bottom_center = ((x1 + x2) / 2.0, y2)

                # Get or create track state
                if track_id not in self.tracks:
                    self.tracks[track_id] = TrackState(
                        track_id=track_id,
                        center_history=deque(maxlen=self.history_length),
                        state_history=deque(maxlen=self.history_length),
                        confidence_history=deque(maxlen=self.history_length),
                    )

                state = self.tracks[track_id]
                state.bbox = [x1, y1, x2, y2]
                state.center = center
                state.bottom_center = bottom_center
                state.class_id = cls_id
                state.class_name = cls_name
                state.confidence = conf
                state.frame_idx = self.frame_count
                state.timestamp = ts
                state.image_width = img_w
                state.image_height = img_h

                # Update histories
                state.center_history.append(center)
                state.state_history.append(cls_name)
                state.confidence_history.append(conf)

                active_tracks.append(state)

        return active_tracks

    def reset(self) -> None:
        """Reset all tracks and frame counter."""
        self.tracks.clear()
        self.frame_count = 0
        # Re-create model to reset tracker state
        model_path = self.model.model_name if hasattr(self.model, 'model_name') else "yolov8n.pt"
        self.model = YOLO(str(model_path))

    def get_track(self, track_id: int) -> TrackState | None:
        """Get a specific track state."""
        return self.tracks.get(track_id)

    def get_all_tracks(self) -> dict[int, TrackState]:
        """Get all track states."""
        return dict(self.tracks)

    @classmethod
    def from_config(
        cls,
        training_config: Path,
        temporal_config: Path,
        model_path: Path | None = None,
    ) -> "PatientTracker":
        """Create a PatientTracker from config files."""
        with open(training_config, "r", encoding="utf-8") as f:
            t_cfg = yaml.safe_load(f)
        with open(temporal_config, "r", encoding="utf-8") as f:
            tmp_cfg = yaml.safe_load(f)

        weights = model_path or t_cfg["model"]["weights"]
        return cls(
            model_path=weights,
            device=t_cfg["training"]["device"],
            imgsz=t_cfg["training"]["imgsz"],
            tracker_config=tmp_cfg["tracking"].get(
                "tracker_config", "bytetrack.yaml"
            ),
            history_length=tmp_cfg["movement"].get("history_length", 60),
        )
