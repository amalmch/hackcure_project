"""
Discomfort Detection Module
===========================
Associates possible_discomfort detections (if available from YOLO)
with tracked patient bounding boxes.

NOTE: The 'nopain' class from the Human Fall Dataset v2 is EXCLUDED
because it represents absence of discomfort and is not a meaningful
detection target. The 'possible_discomfort' class will only be active
if compatible bounding-box annotations existed in the source data.
"""

import logging
import math
from typing import Any

import yaml
from pathlib import Path

logger = logging.getLogger(__name__)


def compute_iou(box_a: list[float], box_b: list[float]) -> float:
    """
    Compute IoU between two boxes in [x1, y1, x2, y2] format.
    """
    x1 = max(box_a[0], box_b[0])
    y1 = max(box_a[1], box_b[1])
    x2 = min(box_a[2], box_b[2])
    y2 = min(box_a[3], box_b[3])

    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    area_a = (box_a[2] - box_a[0]) * (box_a[3] - box_a[1])
    area_b = (box_b[2] - box_b[0]) * (box_b[3] - box_b[1])
    union = area_a + area_b - intersection

    return intersection / union if union > 0 else 0.0


def compute_center_distance(
    box_a: list[float],
    box_b: list[float],
    image_width: int,
    image_height: int,
) -> float:
    """Compute normalized center-to-center distance."""
    cx_a = (box_a[0] + box_a[2]) / 2 / image_width
    cy_a = (box_a[1] + box_a[3]) / 2 / image_height
    cx_b = (box_b[0] + box_b[2]) / 2 / image_width
    cy_b = (box_b[1] + box_b[3]) / 2 / image_height
    return math.sqrt((cx_a - cx_b) ** 2 + (cy_a - cy_b) ** 2)


class DiscomfortAssociator:
    """
    Associates discomfort detections with patient tracks.

    Uses spatial proximity (IoU or center distance) to link
    face/discomfort detections to the nearest patient bounding box.
    """

    DISCOMFORT_CLASS_NAMES = {"possible_discomfort"}

    def __init__(
        self,
        iou_threshold: float = 0.1,
        max_distance: float = 0.3,
        min_confidence: float = 0.30,
    ):
        """
        Args:
            iou_threshold: Min IoU for association.
            max_distance: Max normalized distance for nearest-patient.
            min_confidence: Min detection confidence.
        """
        self.iou_threshold = iou_threshold
        self.max_distance = max_distance
        self.min_confidence = min_confidence

    def associate(
        self,
        detections: list[dict[str, Any]],
        patient_tracks: list[dict[str, Any]],
        image_width: int,
        image_height: int,
    ) -> dict[int, dict[str, Any]]:
        """
        Associate discomfort detections with patient tracks.

        Args:
            detections: All detections from the frame.
            patient_tracks: Active patient track states (as dicts).
            image_width: Frame width.
            image_height: Frame height.

        Returns:
            Dict mapping track_id to discomfort info:
            {
                track_id: {
                    "detected": bool,
                    "confidence": float,
                    "bbox": [x1, y1, x2, y2],
                }
            }
        """
        results: dict[int, dict[str, Any]] = {}

        # Initialize all patients with no discomfort
        for track in patient_tracks:
            tid = track.get("track_id", track.get("patient_id", -1))
            results[tid] = {
                "detected": False,
                "confidence": 0.0,
                "bbox": None,
            }

        # Find discomfort detections
        discomfort_dets = [
            d for d in detections
            if d.get("class_name") in self.DISCOMFORT_CLASS_NAMES
            and d.get("confidence", 0) >= self.min_confidence
        ]

        if not discomfort_dets or not patient_tracks:
            return results

        # Associate each discomfort detection with nearest patient
        for disc_det in discomfort_dets:
            disc_bbox = disc_det["bbox"]
            best_track_id = None
            best_score = -1.0

            for track in patient_tracks:
                tid = track.get("track_id", track.get("patient_id", -1))
                patient_bbox = track.get("bbox", [])

                if len(patient_bbox) < 4:
                    continue

                # Try IoU first
                iou = compute_iou(disc_bbox, patient_bbox)
                if iou >= self.iou_threshold:
                    if iou > best_score:
                        best_score = iou
                        best_track_id = tid
                    continue

                # Fall back to center distance
                dist = compute_center_distance(
                    disc_bbox, patient_bbox,
                    image_width, image_height,
                )
                # Convert distance to score (closer = higher)
                score = max(0, 1.0 - dist / self.max_distance)
                if dist <= self.max_distance and score > best_score:
                    best_score = score
                    best_track_id = tid

            if best_track_id is not None:
                results[best_track_id] = {
                    "detected": True,
                    "confidence": disc_det["confidence"],
                    "bbox": disc_det["bbox"],
                }

        return results

    @classmethod
    def from_config(cls, config_path: Path) -> "DiscomfortAssociator":
        """Create from temporal.yaml config."""
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        d = cfg.get("discomfort", {})
        return cls(
            iou_threshold=d.get("association_iou_threshold", 0.1),
            max_distance=d.get("max_association_distance", 0.3),
            min_confidence=d.get("min_confidence", 0.30),
        )
