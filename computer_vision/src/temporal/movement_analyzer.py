"""
Movement Analyzer
=================
Analyzes temporal movement patterns from tracking data.
Computes velocity, displacement, direction, and movement state.
"""

import logging
import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import yaml
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class MovementState:
    """Movement analysis result for a single tracked patient."""

    track_id: int
    state: str = "stationary"  # stationary, slow, walking, rapid_motion, rapid_downward_motion
    velocity: float = 0.0
    velocity_x: float = 0.0
    velocity_y: float = 0.0
    displacement: float = 0.0
    direction: float = 0.0  # angle in degrees
    magnitude: float = 0.0
    duration_in_state: int = 0  # frames
    time_since_last_movement: int = 0  # frames

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "state": self.state,
            "velocity": round(self.velocity, 6),
            "velocity_x": round(self.velocity_x, 6),
            "velocity_y": round(self.velocity_y, 6),
            "displacement": round(self.displacement, 6),
            "direction": round(self.direction, 2),
            "magnitude": round(self.magnitude, 6),
            "duration_in_state": self.duration_in_state,
            "time_since_last_movement": self.time_since_last_movement,
        }


class MovementAnalyzer:
    """
    Analyzes movement patterns from tracking history.

    Uses normalized coordinates so thresholds are resolution-independent.
    """

    def __init__(
        self,
        stationary_threshold: float = 0.005,
        slow_threshold: float = 0.02,
        walking_threshold: float = 0.06,
        downward_ratio_threshold: float = 0.6,
        rapid_downward_velocity: float = 0.04,
        velocity_smoothing_window: int = 5,
        history_length: int = 30,
    ):
        """
        Initialize movement analyzer.

        Args:
            stationary_threshold: Max velocity for stationary state.
            slow_threshold: Max velocity for slow movement.
            walking_threshold: Max velocity for walking.
            downward_ratio_threshold: Vertical component ratio for downward.
            rapid_downward_velocity: Min velocity for rapid downward.
            velocity_smoothing_window: Frames to average velocity over.
            history_length: Number of frames to keep in history.
        """
        self.stationary_threshold = stationary_threshold
        self.slow_threshold = slow_threshold
        self.walking_threshold = walking_threshold
        self.downward_ratio_threshold = downward_ratio_threshold
        self.rapid_downward_velocity = rapid_downward_velocity
        self.velocity_smoothing_window = velocity_smoothing_window
        self.history_length = history_length

        # Per-track velocity histories and state tracking
        self._velocity_history: dict[int, deque] = {}
        self._state_history: dict[int, deque] = {}
        self._movement_states: dict[int, MovementState] = {}
        self._last_movement_frame: dict[int, int] = {}
        self._frame_count: int = 0

    def update(
        self,
        track_id: int,
        center: tuple[float, float],
        image_width: int,
        image_height: int,
        frame_idx: int,
        center_history: deque | None = None,
    ) -> MovementState:
        """
        Update movement analysis for a track.

        Args:
            track_id: Persistent track ID.
            center: Current center position in pixels.
            image_width: Image width for normalization.
            image_height: Image height for normalization.
            frame_idx: Current frame index.
            center_history: Historical center positions (optional).

        Returns:
            MovementState for this track.
        """
        self._frame_count = frame_idx

        # Normalize center
        norm_x = center[0] / image_width if image_width > 0 else 0
        norm_y = center[1] / image_height if image_height > 0 else 0

        # Initialize histories if needed
        if track_id not in self._velocity_history:
            self._velocity_history[track_id] = deque(
                maxlen=self.history_length
            )
            self._state_history[track_id] = deque(
                maxlen=self.history_length
            )
            self._last_movement_frame[track_id] = frame_idx

        # Compute velocity from history
        if center_history and len(center_history) >= 2:
            # Use the last two positions
            prev = center_history[-2]
            prev_x = prev[0] / image_width if image_width > 0 else 0
            prev_y = prev[1] / image_height if image_height > 0 else 0

            vx = norm_x - prev_x
            vy = norm_y - prev_y
        else:
            vx = 0.0
            vy = 0.0

        velocity = math.sqrt(vx * vx + vy * vy)
        self._velocity_history[track_id].append((vx, vy, velocity))

        # Smooth velocity
        window = min(
            self.velocity_smoothing_window,
            len(self._velocity_history[track_id]),
        )
        if window > 0:
            recent = list(self._velocity_history[track_id])[-window:]
            avg_velocity = sum(v[2] for v in recent) / window
            avg_vx = sum(v[0] for v in recent) / window
            avg_vy = sum(v[1] for v in recent) / window
        else:
            avg_velocity = velocity
            avg_vx = vx
            avg_vy = vy

        # Compute displacement (total accumulated movement)
        displacement = sum(
            v[2] for v in self._velocity_history[track_id]
        )

        # Direction (angle in degrees, 0 = right, 90 = down)
        direction = math.degrees(math.atan2(avg_vy, avg_vx)) if avg_velocity > 0.001 else 0.0

        # Determine movement state
        downward_ratio = abs(avg_vy) / (avg_velocity + 1e-8)
        is_downward = (
            avg_vy > 0
            and downward_ratio > self.downward_ratio_threshold
        )

        if (
            avg_velocity >= self.rapid_downward_velocity
            and is_downward
        ):
            state = "rapid_downward_motion"
        elif avg_velocity < self.stationary_threshold:
            state = "stationary"
        elif avg_velocity < self.slow_threshold:
            state = "slow"
        elif avg_velocity < self.walking_threshold:
            state = "walking"
        else:
            state = "rapid_motion"

        # Track state duration
        prev_state = self._state_history[track_id][-1] if self._state_history[track_id] else None
        self._state_history[track_id].append(state)

        duration = 0
        for s in reversed(self._state_history[track_id]):
            if s == state:
                duration += 1
            else:
                break

        # Time since last movement
        if state != "stationary":
            self._last_movement_frame[track_id] = frame_idx
        time_since_movement = (
            frame_idx - self._last_movement_frame.get(track_id, frame_idx)
        )

        movement = MovementState(
            track_id=track_id,
            state=state,
            velocity=avg_velocity,
            velocity_x=avg_vx,
            velocity_y=avg_vy,
            displacement=displacement,
            direction=direction,
            magnitude=avg_velocity,
            duration_in_state=duration,
            time_since_last_movement=time_since_movement,
        )

        self._movement_states[track_id] = movement
        return movement

    def get_state(self, track_id: int) -> MovementState | None:
        """Get the current movement state for a track."""
        return self._movement_states.get(track_id)

    def reset(self) -> None:
        """Reset all movement analysis state."""
        self._velocity_history.clear()
        self._state_history.clear()
        self._movement_states.clear()
        self._last_movement_frame.clear()
        self._frame_count = 0

    @classmethod
    def from_config(cls, config_path: Path) -> "MovementAnalyzer":
        """Create from temporal.yaml config."""
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        m = cfg.get("movement", {})
        return cls(
            stationary_threshold=m.get("stationary_threshold", 0.005),
            slow_threshold=m.get("slow_threshold", 0.02),
            walking_threshold=m.get("walking_threshold", 0.06),
            downward_ratio_threshold=m.get("downward_ratio_threshold", 0.6),
            rapid_downward_velocity=m.get("rapid_downward_velocity", 0.04),
            velocity_smoothing_window=m.get("velocity_smoothing_window", 5),
            history_length=m.get("history_length", 30),
        )
