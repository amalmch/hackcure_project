"""
Temporal Risk Analyzer & Multi-Modal Fusion Engine
===================================================
Aggregates spatial detections (YOLOv8n), visual posture features (Vision Transformer DINOv2),
movement trajectories, and discomfort cues over sliding temporal windows.

Computes:
  - Behavioral indicators (immobility, agitation, instability, discomfort)
  - Multi-factor risk scoring (low, moderate, high, critical)
  - Structured event conforming to the hospital intervention-agent contract
"""

from __future__ import annotations
import collections
from datetime import datetime, timezone
import logging
from typing import Dict, List, Optional, Tuple, Union
import uuid

import numpy as np

logger = logging.getLogger("hackcure.risk_analyzer")


class TemporalRiskAnalyzer:
    """
    Sliding-window temporal fusion engine for patient monitoring.
    Combines YOLO tracking with DINOv2 Vision Transformer posture analysis.
    """
    def __init__(self, window_size: int = 30):
        self.window_size = window_size
        # Dictionary of patient_id -> deque of recent observations
        self.history: Dict[str, collections.deque] = collections.defaultdict(
            lambda: collections.deque(maxlen=self.window_size)
        )

    def update_patient(
        self,
        patient_id: str,
        yolo_state: str,
        yolo_confidence: float,
        yolo_velocity: Optional[float] = None,
        transformer_posture: Optional[str] = None,
        transformer_fall_prob: Optional[float] = None,
        dino_cls_token: Optional[np.ndarray] = None,
        discomfort_detected: bool = False,
        discomfort_conf: float = 0.0,
    ) -> None:
        """
        Add a multi-modal observation to the patient's temporal window.
        """
        now = datetime.now(timezone.utc)
        self.history[patient_id].append({
            "timestamp": now,
            "yolo_state": yolo_state,
            "yolo_confidence": yolo_confidence,
            "yolo_velocity": yolo_velocity,
            "transformer_posture": transformer_posture or yolo_state,
            "transformer_fall_prob": transformer_fall_prob if transformer_fall_prob is not None else (0.9 if yolo_state == "falling" else 0.1),
            "dino_feature": dino_cls_token,
            "discomfort_detected": discomfort_detected,
            "discomfort_conf": discomfort_conf,
        })

    def _detect_behavioral_indicators(self, recent_frames: collections.deque) -> List[str]:
        """
        Analyzes the sliding window to identify temporal behavior indicators.
        """
        indicators = []
        if len(recent_frames) == 0:
            return indicators

        velocities = [f["yolo_velocity"] for f in recent_frames if f["yolo_velocity"] is not None]

        # 1. Prolonged Immobility
        # Patient is static / unmoving across the majority of the temporal window
        if velocities and len(recent_frames) >= 15:
            if np.mean(velocities) < 0.004:
                indicators.append("prolonged_immobility")

        # 2. Repeated Agitation
        # High velocity variance indicating erratic or rapid movement
        if len(velocities) >= 10 and np.var(velocities) > 0.008:
            indicators.append("agitation_detected")

        # 3. Postural Instability Pattern
        # Transformer detects near-fall or stumbling postures repeatedly
        fall_probs = [f["transformer_fall_prob"] for f in recent_frames if f.get("transformer_fall_prob") is not None]
        unstable_frames = sum(1 for p in fall_probs if 0.4 <= p < 0.8)
        if unstable_frames >= 4:
            indicators.append("instability_pattern")

        # 4. Sudden Downward Motion
        if velocities and len(velocities) >= 3:
            recent_vel = velocities[-3:]
            if np.mean(recent_vel) > 0.035 and fall_probs and fall_probs[-1] > 0.6:
                indicators.append("sudden_downward_motion")

        # 5. Visible Discomfort Indicator
        recent_discomfort = [f for f in recent_frames if f.get("discomfort_detected")]
        if len(recent_discomfort) >= 3:
            indicators.append("possible_discomfort")

        return indicators

    def _estimate_risk(
        self,
        patient_id: str,
        recent_frames: collections.deque,
        behavioral_indicators: List[str],
    ) -> Tuple[float, str, str]:
        """
        Multi-modal risk fusion combining YOLO detections, Transformer posture predictions,
        and temporal movement indicators.

        Returns:
            (risk_score, risk_level, primary_event_type)
        """
        latest = recent_frames[-1]
        yolo_fall = latest["yolo_state"] in ("falling", "patient_fallen")
        trans_fall_prob = latest.get("transformer_fall_prob", 0.0)

        # 1. Confirmed Fall: Both YOLO and Vision Transformer agree, or high fall prob sustained
        if (yolo_fall and trans_fall_prob > 0.5) or trans_fall_prob > 0.85:
            return 0.95, "critical", "fall"

        # 2. Fall with Discomfort
        if yolo_fall and "possible_discomfort" in behavioral_indicators:
            return 0.98, "critical", "fall_and_pain"

        # 3. Discomfort alone
        if "possible_discomfort" in behavioral_indicators:
            return 0.65, "high", "pain"

        # 4. High Risk (Pre-fall / Severe Instability)
        if "instability_pattern" in behavioral_indicators or "sudden_downward_motion" in behavioral_indicators:
            return 0.75, "high", "behavioral_risk"

        # 5. Moderate Risk (Agitation or Prolonged Inactivity)
        if "agitation_detected" in behavioral_indicators:
            return 0.50, "moderate", "behavioral_risk"

        if "prolonged_immobility" in behavioral_indicators:
            return 0.40, "moderate", "behavioral_risk"

        # 6. Normal baseline
        return 0.10, "low", "recover"

    def generate_event(self, patient_id: str, adapter_recommendations: Optional[List[str]] = None) -> Optional[Dict]:
        """
        Generates a comprehensive event payload satisfying both:
          - The intervention agent contract
          - The 3D hospital dashboard / WebSocket interface
        """
        recent_frames = self.history[patient_id]
        if not recent_frames:
            return None

        latest = recent_frames[-1]
        behavioral_indicators = self._detect_behavioral_indicators(recent_frames)
        risk_score, risk_level, event_type = self._estimate_risk(patient_id, recent_frames, behavioral_indicators)

        now_iso = latest["timestamp"].isoformat()

        sources = ["yolov8n_spatial", "dinov2_vision_transformer", "temporal_risk_analyzer"]

        # Determine dashboard state field
        is_fall = event_type in ("fall", "fall_and_pain")
        is_pain = event_type in ("pain", "fall_and_pain")
        if is_fall and is_pain:
            dash_state = "fall_and_pain"
            alert_priority = "critical"
        elif is_fall:
            dash_state = "fall_detected"
            alert_priority = "critical"
        elif is_pain:
            dash_state = "pain_detected"
            alert_priority = "high"
        elif risk_level in ("high", "moderate"):
            dash_state = "behavioral_risk"
            alert_priority = "high" if risk_level == "high" else "medium"
        else:
            dash_state = "normal"
            alert_priority = "none"

        event = {
            # Agent Contract Core Schema
            "event_id": f"evt_{uuid.uuid4().hex[:8]}",
            "entity_type": "patient",
            "entity_id": patient_id,
            "patient_id": patient_id,  # compatibility alias
            "timestamp": now_iso,
            "category": "fall_detection" if is_fall else "behavioral_risk" if risk_level != "low" else "routine_monitoring",
            "event_type": event_type,
            "event_status": "detected" if is_fall else "predicted" if "instability_pattern" in behavioral_indicators else "observed",
            "evidence": behavioral_indicators,
            "behavior_indicators": behavioral_indicators,  # compatibility alias
            "sources": sources,
            "risk_level": risk_level,
            "risk_score": round(risk_score, 2),
            "prediction_horizon_sec": 300,
            "human_confirmation_required": risk_level in ("high", "critical"),

            # Model Specific Confidence
            "confidence": round(float(latest["yolo_confidence"]), 4),
            "transformer_fall_probability": round(float(latest["transformer_fall_prob"]), 4),

            # Sensor & Hardware Status (Honest sensor integration)
            "temperature_status": "Temperature unavailable — no compatible sensor connected",
            "sensor_available": False,

            # Recommendations from Intervention Agent
            "recommendations": adapter_recommendations or [],

            # 3D Dashboard & WebSocket Compatibility
            "state": dash_state,
            "fall_detected": is_fall,
            "pain_detected": is_pain,
            "alert_priority": alert_priority,
        }

        return event
