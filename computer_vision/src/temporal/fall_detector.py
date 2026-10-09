"""
Temporal Fall Detector
======================
Detects fall events using temporal state sequences rather than
single-frame YOLO detections alone.

Evaluates:
- YOLO detection class + confidence
- State transition sequences (standing → inclined → fallen)
- Rapid downward movement
- Post-fall stillness
- Persistence of fallen state
"""

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Classes that represent "fallen" or precursor states
FALLEN_CLASSES = {"patient_fallen"}
NEAR_FALL_CLASSES = {"patient_near_fall", "patient_inclined"}
UPRIGHT_CLASSES = {
    "patient_standing", "patient_sitting", "patient_lying",
    "patient_moving_out", "patient_out",
}


@dataclass
class FallEvent:
    """Represents a detected fall event."""

    track_id: int
    detected: bool = False
    confidence: float = 0.0
    start_frame: int = 0
    confirmed_frame: int = 0
    detection_delay_frames: int = 0
    timestamp: float = 0.0
    state_sequence: list[str] = field(default_factory=list)
    contributing_factors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "detected": self.detected,
            "confidence": round(self.confidence, 4),
            "start_frame": self.start_frame,
            "confirmed_frame": self.confirmed_frame,
            "detection_delay_frames": self.detection_delay_frames,
            "timestamp": round(self.timestamp, 3),
            "state_sequence": self.state_sequence[-10:],
            "contributing_factors": self.contributing_factors,
        }


class FallDetector:
    """
    Temporal fall detector using multi-frame evidence.

    A fall is confirmed when:
    1. YOLO detects 'patient_fallen' with sufficient confidence
    2. The state transition is consistent (upright → near_fall → fallen)
    3. Rapid downward movement was observed
    4. The patient remains stationary after the fall
    """

    def __init__(
        self,
        min_fallen_frames: int = 5,
        min_fallen_confidence: float = 0.35,
        transition_window: int = 15,
        post_fall_stationary_frames: int = 8,
        post_fall_max_velocity: float = 0.01,
        rapid_downward_boost: float = 0.15,
        state_transition_boost: float = 0.10,
        persistence_boost: float = 0.10,
        min_fall_event_confidence: float = 0.50,
        max_acceptable_delay_frames: int = 30,
    ):
        """Initialize fall detector with configurable thresholds."""
        self.min_fallen_frames = min_fallen_frames
        self.min_fallen_confidence = min_fallen_confidence
        self.transition_window = transition_window
        self.post_fall_stationary_frames = post_fall_stationary_frames
        self.post_fall_max_velocity = post_fall_max_velocity
        self.rapid_downward_boost = rapid_downward_boost
        self.state_transition_boost = state_transition_boost
        self.persistence_boost = persistence_boost
        self.min_fall_event_confidence = min_fall_event_confidence
        self.max_acceptable_delay_frames = max_acceptable_delay_frames

        # Per-track state
        self._state_buffers: dict[int, deque] = {}
        self._confidence_buffers: dict[int, deque] = {}
        self._movement_buffers: dict[int, deque] = {}
        self._active_falls: dict[int, FallEvent] = {}
        self._confirmed_falls: list[FallEvent] = []
        self._potential_fall_start: dict[int, int] = {}

    def update(
        self,
        track_id: int,
        class_name: str,
        confidence: float,
        movement_state: str,
        velocity: float,
        frame_idx: int,
        timestamp: float = 0.0,
    ) -> FallEvent:
        """
        Update fall detection for a tracked patient.

        Args:
            track_id: Persistent track ID.
            class_name: Current YOLO detection class.
            confidence: Detection confidence.
            movement_state: From MovementAnalyzer.
            velocity: Current velocity (normalized).
            frame_idx: Current frame index.
            timestamp: Current timestamp.

        Returns:
            FallEvent with current status.
        """
        # Initialize buffers
        if track_id not in self._state_buffers:
            buf_len = self.transition_window * 2
            self._state_buffers[track_id] = deque(maxlen=buf_len)
            self._confidence_buffers[track_id] = deque(maxlen=buf_len)
            self._movement_buffers[track_id] = deque(maxlen=buf_len)

        self._state_buffers[track_id].append(class_name)
        self._confidence_buffers[track_id].append(confidence)
        self._movement_buffers[track_id].append(
            (movement_state, velocity)
        )

        # Get or create fall event
        if track_id not in self._active_falls:
            self._active_falls[track_id] = FallEvent(track_id=track_id)

        event = self._active_falls[track_id]
        event.timestamp = timestamp

        # Check if currently in fallen state
        is_fallen = class_name in FALLEN_CLASSES
        has_sufficient_confidence = confidence >= self.min_fallen_confidence

        if not is_fallen or not has_sufficient_confidence:
            # Not currently fallen - check if we need to reset
            if event.detected:
                # Was previously detected - check if recovery
                recent_states = list(self._state_buffers[track_id])[-5:]
                if all(s not in FALLEN_CLASSES for s in recent_states):
                    # Patient has recovered
                    event.detected = False
                    event.confidence = 0.0
            return event

        # ---------- FALLEN STATE DETECTED ----------

        # Mark potential fall start
        if track_id not in self._potential_fall_start:
            self._potential_fall_start[track_id] = frame_idx
            event.start_frame = frame_idx

        # Count consecutive fallen frames
        fallen_count = 0
        for s in reversed(self._state_buffers[track_id]):
            if s in FALLEN_CLASSES:
                fallen_count += 1
            else:
                break

        if fallen_count < self.min_fallen_frames:
            # Not enough evidence yet
            event.state_sequence = list(
                self._state_buffers[track_id]
            )[-10:]
            return event

        # ---------- COMPUTE FALL CONFIDENCE ----------

        base_confidence = confidence
        factors = []

        # Factor 1: State transition (upright → near_fall → fallen)
        recent_window = list(
            self._state_buffers[track_id]
        )[-self.transition_window:]
        had_upright = any(s in UPRIGHT_CLASSES for s in recent_window)
        had_near_fall = any(
            s in NEAR_FALL_CLASSES for s in recent_window
        )

        if had_upright:
            base_confidence += self.state_transition_boost
            factors.append("state_transition_from_upright")
        if had_near_fall:
            base_confidence += self.state_transition_boost * 0.5
            factors.append("preceded_by_near_fall")

        # Factor 2: Rapid downward movement
        recent_movements = list(
            self._movement_buffers[track_id]
        )[-self.transition_window:]
        had_rapid_down = any(
            m[0] == "rapid_downward_motion" for m in recent_movements
        )
        if had_rapid_down:
            base_confidence += self.rapid_downward_boost
            factors.append("rapid_downward_movement")

        # Factor 3: Post-fall stillness
        recent_velocities = [
            m[1] for m in list(
                self._movement_buffers[track_id]
            )[-self.post_fall_stationary_frames:]
        ]
        if (
            len(recent_velocities) >= self.post_fall_stationary_frames
            and all(v <= self.post_fall_max_velocity for v in recent_velocities)
        ):
            base_confidence += self.persistence_boost
            factors.append("post_fall_stationary")

        # Factor 4: Persistence
        if fallen_count >= self.min_fallen_frames * 2:
            base_confidence += self.persistence_boost
            factors.append("persistent_fallen_state")

        # Clamp confidence
        base_confidence = min(1.0, max(0.0, base_confidence))

        # Check threshold
        if base_confidence >= self.min_fall_event_confidence:
            event.detected = True
            event.confidence = base_confidence
            event.confirmed_frame = frame_idx
            event.detection_delay_frames = (
                frame_idx - self._potential_fall_start.get(
                    track_id, frame_idx
                )
            )
            event.contributing_factors = factors
            event.state_sequence = list(
                self._state_buffers[track_id]
            )[-10:]

            # Record confirmed fall
            if event not in self._confirmed_falls:
                self._confirmed_falls.append(event)
                logger.info(
                    f"FALL CONFIRMED: Track {track_id}, "
                    f"confidence={base_confidence:.3f}, "
                    f"delay={event.detection_delay_frames} frames, "
                    f"factors={factors}"
                )

        return event

    def get_fall_event(self, track_id: int) -> FallEvent | None:
        """Get the current fall event for a track."""
        return self._active_falls.get(track_id)

    def get_all_confirmed_falls(self) -> list[FallEvent]:
        """Get all confirmed fall events."""
        return list(self._confirmed_falls)

    def reset(self) -> None:
        """Reset all fall detection state."""
        self._state_buffers.clear()
        self._confidence_buffers.clear()
        self._movement_buffers.clear()
        self._active_falls.clear()
        self._confirmed_falls.clear()
        self._potential_fall_start.clear()

    @classmethod
    def from_config(cls, config_path: Path) -> "FallDetector":
        """Create from temporal.yaml config."""
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        fd = cfg.get("fall_detection", {})
        return cls(
            min_fallen_frames=fd.get("min_fallen_frames", 5),
            min_fallen_confidence=fd.get("min_fallen_confidence", 0.35),
            transition_window=fd.get("transition_window", 15),
            post_fall_stationary_frames=fd.get(
                "post_fall_stationary_frames", 8
            ),
            post_fall_max_velocity=fd.get("post_fall_max_velocity", 0.01),
            rapid_downward_boost=fd.get("rapid_downward_boost", 0.15),
            state_transition_boost=fd.get("state_transition_boost", 0.10),
            persistence_boost=fd.get("persistence_boost", 0.10),
            min_fall_event_confidence=fd.get(
                "min_fall_event_confidence", 0.50
            ),
            max_acceptable_delay_frames=fd.get(
                "max_acceptable_delay_frames", 30
            ),
        )
