"""
Patient Detector
================
Wraps the YOLOv8n model for patient detection inference.
Provides structured detection results.
"""

import logging
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from ultralytics import YOLO

logger = logging.getLogger(__name__)


class PatientDetector:
    """YOLOv8n-based patient detector."""

    def __init__(
        self,
        model_path: str | Path = "yolov8n.pt",
        confidence: float = 0.25,
        iou_threshold: float = 0.45,
        device: str | int = "0",
        imgsz: int = 640,
    ):
        """
        Initialize the patient detector.

        Args:
            model_path: Path to YOLOv8n weights (best.pt or yolov8n.pt).
            confidence: Minimum confidence threshold.
            iou_threshold: NMS IoU threshold.
            device: CUDA device or 'cpu'.
            imgsz: Inference image size.
        """
        self.model_path = Path(model_path)
        self.confidence = confidence
        self.iou_threshold = iou_threshold
        self.device = device
        self.imgsz = imgsz

        logger.info(f"Loading model from {self.model_path}")
        self.model = YOLO(str(self.model_path))
        self.class_names = self.model.names
        logger.info(f"Model loaded. Classes: {self.class_names}")

    def detect(
        self,
        source: str | Path | np.ndarray,
        verbose: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Run detection on a single image/frame.

        Args:
            source: Image path, numpy array (BGR), or video path.
            verbose: Whether to print YOLO verbose output.

        Returns:
            List of detection dicts, each containing:
            - bbox: [x1, y1, x2, y2] in pixels
            - bbox_norm: [x_c, y_c, w, h] normalized
            - class_id: int
            - class_name: str
            - confidence: float
        """
        results = self.model.predict(
            source=source,
            conf=self.confidence,
            iou=self.iou_threshold,
            device=self.device,
            imgsz=self.imgsz,
            verbose=verbose,
        )

        detections = []
        for result in results:
            if result.boxes is None:
                continue

            img_h, img_w = result.orig_shape

            for i in range(len(result.boxes)):
                box = result.boxes[i]
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                conf = float(box.conf[0].cpu().numpy())
                cls_id = int(box.cls[0].cpu().numpy())
                cls_name = self.class_names.get(cls_id, f"class_{cls_id}")

                # Normalized coordinates
                x_c = ((x1 + x2) / 2) / img_w
                y_c = ((y1 + y2) / 2) / img_h
                w = (x2 - x1) / img_w
                h = (y2 - y1) / img_h

                detections.append({
                    "bbox": [float(x1), float(y1), float(x2), float(y2)],
                    "bbox_norm": [float(x_c), float(y_c), float(w), float(h)],
                    "class_id": cls_id,
                    "class_name": cls_name,
                    "confidence": conf,
                    "image_width": img_w,
                    "image_height": img_h,
                })

        return detections

    def detect_batch(
        self,
        sources: list[str | Path | np.ndarray],
        verbose: bool = False,
    ) -> list[list[dict[str, Any]]]:
        """Run detection on a batch of images."""
        all_detections = []
        for source in sources:
            dets = self.detect(source, verbose=verbose)
            all_detections.append(dets)
        return all_detections

    @classmethod
    def from_config(cls, config_path: Path, model_path: Path | None = None) -> "PatientDetector":
        """
        Create a PatientDetector from a training config file.

        Args:
            config_path: Path to training.yaml.
            model_path: Override model weights path.
        """
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        weights = model_path or config["model"]["weights"]
        return cls(
            model_path=weights,
            device=config["training"]["device"],
            imgsz=config["training"]["imgsz"],
        )
