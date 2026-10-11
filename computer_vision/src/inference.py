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
from .temporal.risk_analyzer import TemporalRiskAnalyzer
from .temporal.agent_adapter import InterventionAgentAdapter
from .behavior import load_transformer  # transformer optionnel : None si PyTorch, le backbone ou les poids manquent

CV_DIR = Path(__file__).resolve().parent.parent
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

        # Vision Transformer & Temporal Decision Integration
        self.device = device
        self.temporal_risk_analyzer = TemporalRiskAnalyzer(window_size=30)
        self.agent_adapter = InterventionAgentAdapter()
        self.transformer = None

        self.transformer = load_transformer(device)  # repli automatique sur YOLO + analyse temporelle

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

            # Step 6: Vision Transformer Feature & Posture Extraction
            x1, y1, x2, y2 = [int(v) for v in track.bbox]
            crop_bgr = frame[max(0, y1):min(img_h, y2), max(0, x1):min(img_w, x2)]
            trans_result = None
            fall_prob = 0.9 if track.class_name == "falling" else 0.1
            posture_pred = track.class_name

            if self.transformer is not None and crop_bgr.size > 0:
                try:
                    crop_rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
                    trans_result = self.transformer.predict_crop(crop_rgb)
                    fall_prob = trans_result.get("fall_probability", fall_prob)
                    posture_pred = trans_result.get("class_name", posture_pred)
                except Exception as e:
                    logger.debug(f"Transformer crop prediction error: {e}")

            # Step 7: Temporal Risk & Behavior Analysis
            patient_str_id = f"patient_{track.track_id:02d}"
            self.temporal_risk_analyzer.update_patient(
                patient_id=patient_str_id,
                yolo_state=track.class_name,
                yolo_confidence=track.confidence,
                yolo_velocity=movement.velocity,
                transformer_posture=posture_pred,
                transformer_fall_prob=fall_prob,
                discomfort_detected=disc.get("detected", False),
                discomfort_conf=disc.get("confidence", 0.0),
            )
            event_payload = self.temporal_risk_analyzer.generate_event(patient_str_id)
            recs = self.agent_adapter.request_recommendation(event_payload) if event_payload else []
            if event_payload:
                event_payload["recommendations"] = recs

            # Build enriched structured output
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
                "transformer_analysis": trans_result,
                "risk_level": event_payload.get("risk_level", "low") if event_payload else "low",
                "risk_score": event_payload.get("risk_score", 0.0) if event_payload else 0.0,
                "behavior_indicators": event_payload.get("evidence", []) if event_payload else [],
                "recommendations": recs,
                "event_payload": event_payload,
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
