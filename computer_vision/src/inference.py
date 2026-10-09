"""
Inference Engine
================
Unified inference pipeline that integrates detection, tracking,
movement analysis, fall detection, discomfort association,
and spatial positioning into structured patient outputs.
"""

import logging
import time
from pathlib import Path
from typing import Any, Generator

import cv2
import numpy as np
import yaml

from .tracking.patient_tracker import PatientTracker
from .temporal.movement_analyzer import MovementAnalyzer
from .temporal.fall_detector import FallDetector
from .face.discomfort import DiscomfortAssociator
from .spatial.position import compute_position
from .visualization import annotate_frame

logger = logging.getLogger(__name__)


class PatientMonitor:
    """
    Full inference pipeline for patient monitoring.

    Integrates:
    - YOLOv8n detection + ByteTrack tracking
    - Temporal movement analysis
    - Fall event detection
    - Discomfort association
    - Spatial positioning
    """

    def __init__(
        self,
        model_path: str | Path,
        confidence: float = 0.25,
        iou_threshold: float = 0.45,
        device: str | int = "0",
        imgsz: int = 640,
        temporal_config: Path | None = None,
    ):
        """
        Initialize the patient monitoring pipeline.

        Args:
            model_path: Path to trained YOLOv8n weights.
            confidence: Detection confidence threshold.
            iou_threshold: NMS IoU threshold.
            device: CUDA device or 'cpu'.
            imgsz: Inference image size.
            temporal_config: Path to temporal.yaml for thresholds.
        """
        self.tracker = PatientTracker(
            model_path=model_path,
            confidence=confidence,
            iou_threshold=iou_threshold,
            device=device,
            imgsz=imgsz,
        )

        if temporal_config and temporal_config.exists():
            self.movement_analyzer = MovementAnalyzer.from_config(
                temporal_config
            )
            self.fall_detector = FallDetector.from_config(temporal_config)
            self.discomfort_associator = DiscomfortAssociator.from_config(
                temporal_config
            )
        else:
            self.movement_analyzer = MovementAnalyzer()
            self.fall_detector = FallDetector()
            self.discomfort_associator = DiscomfortAssociator()

        self.class_names = self.tracker.class_names

    def process_frame(
        self,
        frame: np.ndarray,
        timestamp: float | None = None,
    ) -> list[dict[str, Any]]:
        """
        Process a single frame through the full pipeline.

        Args:
            frame: BGR numpy array.
            timestamp: Optional timestamp in seconds.

        Returns:
            List of structured patient output dicts.
        """
        # Step 1: Detect + Track
        tracks = self.tracker.update(frame, timestamp)

        if not tracks:
            return []

        img_h, img_w = frame.shape[:2]
        ts = timestamp if timestamp is not None else self.tracker.frame_count / 30.0

        patient_outputs = []

        # Collect all detections for discomfort association
        all_detections = []
        track_dicts = []

        for track in tracks:
            det = {
                "bbox": track.bbox,
                "class_name": track.class_name,
                "confidence": track.confidence,
                "track_id": track.track_id,
            }
            all_detections.append(det)
            track_dicts.append({
                "track_id": track.track_id,
                "bbox": track.bbox,
            })

        # Discomfort association
        discomfort_results = self.discomfort_associator.associate(
            detections=all_detections,
            patient_tracks=track_dicts,
            image_width=img_w,
            image_height=img_h,
        )

        for track in tracks:
            # Step 2: Movement analysis
            movement = self.movement_analyzer.update(
                track_id=track.track_id,
                center=track.center,
                image_width=img_w,
                image_height=img_h,
                frame_idx=self.tracker.frame_count,
                center_history=track.center_history,
            )

            # Step 3: Fall detection
            fall_event = self.fall_detector.update(
                track_id=track.track_id,
                class_name=track.class_name,
                confidence=track.confidence,
                movement_state=movement.state,
                velocity=movement.velocity,
                frame_idx=self.tracker.frame_count,
                timestamp=ts,
            )

            # Step 4: Spatial position
            position = compute_position(
                bbox=track.bbox,
                image_width=img_w,
                image_height=img_h,
            )

            # Step 5: Discomfort
            disc = discomfort_results.get(
                track.track_id,
                {"detected": False, "confidence": 0.0},
            )

            # Build structured output
            output = {
                "patient_id": track.track_id,
                "timestamp": round(ts, 3),
                "bbox": [round(v, 1) for v in track.bbox],
                "state": track.class_name,
                "confidence": round(track.confidence, 4),
                "position": position.to_dict(),
                "movement": movement.to_dict(),
                "fall_event": fall_event.to_dict(),
                "possible_discomfort": {
                    "detected": disc.get("detected", False),
                    "confidence": round(
                        disc.get("confidence", 0.0), 4
                    ),
                },
                "trajectory": list(track.center_history),
            }
            patient_outputs.append(output)

        return patient_outputs

    def process_video(
        self,
        video_path: str | Path | int,
        visualize: bool = True,
        save_video: bool = False,
        output_video_path: Path | None = None,
        display: bool = True,
        max_frames: int | None = None,
    ) -> Generator[tuple[np.ndarray, list[dict[str, Any]]], None, None]:
        """
        Process a video source frame by frame.

        Args:
            video_path: Video file path, webcam index, or stream URL.
            visualize: Whether to draw annotations on frames.
            save_video: Whether to save annotated video.
            output_video_path: Path for saved video.
            display: Whether to display frames in a window.
            max_frames: Maximum frames to process.

        Yields:
            Tuple of (annotated_frame, patient_outputs).
        """
        source = int(video_path) if str(video_path).isdigit() else str(video_path)
        cap = cv2.VideoCapture(source)

        if not cap.isOpened():
            logger.error(f"Could not open video source: {video_path}")
            return

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        logger.info(
            f"Processing video: {video_path} "
            f"(FPS={fps:.1f}, frames={total_frames})"
        )

        writer = None
        if save_video and output_video_path:
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            output_video_path.parent.mkdir(parents=True, exist_ok=True)
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(
                str(output_video_path), fourcc, fps, (w, h)
            )

        frame_idx = 0
        try:
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break

                if max_frames and frame_idx >= max_frames:
                    break

                timestamp = frame_idx / fps
                patient_outputs = self.process_frame(frame, timestamp)

                if visualize:
                    annotated = annotate_frame(frame, patient_outputs)
                else:
                    annotated = frame

                if writer:
                    writer.write(annotated)

                if display:
                    cv2.imshow("Patient Monitor", annotated)
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord("q") or key == 27:
                        break

                yield annotated, patient_outputs
                frame_idx += 1

        finally:
            cap.release()
            if writer:
                writer.release()
            if display:
                cv2.destroyAllWindows()

        logger.info(f"Processed {frame_idx} frames")

    def process_image(
        self,
        image_path: str | Path,
        visualize: bool = True,
    ) -> tuple[np.ndarray, list[dict[str, Any]]]:
        """
        Process a single image.

        Returns:
            Tuple of (annotated_frame, patient_outputs).
        """
        frame = cv2.imread(str(image_path))
        if frame is None:
            logger.error(f"Could not read image: {image_path}")
            return np.array([]), []

        patient_outputs = self.process_frame(frame)

        if visualize:
            annotated = annotate_frame(frame, patient_outputs)
        else:
            annotated = frame

        return annotated, patient_outputs

    def reset(self) -> None:
        """Reset all internal state."""
        self.tracker.reset()
        self.movement_analyzer.reset()
        self.fall_detector.reset()

    @classmethod
    def from_config(
        cls,
        training_config: Path,
        temporal_config: Path,
        model_path: Path | None = None,
    ) -> "PatientMonitor":
        """Create from config files."""
        with open(training_config, "r", encoding="utf-8") as f:
            t_cfg = yaml.safe_load(f)

        weights = model_path or t_cfg["model"]["weights"]
        return cls(
            model_path=weights,
            device=t_cfg["training"]["device"],
            imgsz=t_cfg["training"]["imgsz"],
            temporal_config=temporal_config,
        )
