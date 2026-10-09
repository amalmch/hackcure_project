"""
Visualization Module
====================
Draws bounding boxes, tracking IDs, trajectories, fall status,
and discomfort indicators on frames.
"""

import logging
from pathlib import Path
from typing import Any

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Color palette (BGR) - distinct colors per class
CLASS_COLORS = {
    "patient_fallen": (0, 0, 255),        # Red
    "patient_near_fall": (0, 128, 255),    # Orange
    "patient_lying": (255, 200, 0),        # Cyan-ish
    "patient_sitting": (255, 255, 0),      # Cyan
    "patient_moving_out": (0, 255, 255),   # Yellow
    "patient_out": (128, 128, 128),        # Gray
    "patient_standing": (0, 255, 0),       # Green
    "patient_inclined": (0, 165, 255),     # Orange
    "possible_discomfort": (255, 0, 255),  # Magenta
}
DEFAULT_COLOR = (200, 200, 200)

FALL_ALERT_COLOR = (0, 0, 255)
DISCOMFORT_ALERT_COLOR = (255, 0, 255)


def get_color(class_name: str) -> tuple[int, int, int]:
    """Get color for a class name."""
    return CLASS_COLORS.get(class_name, DEFAULT_COLOR)


def draw_detection(
    frame: np.ndarray,
    bbox: list[float],
    class_name: str,
    confidence: float,
    track_id: int | None = None,
    color: tuple[int, int, int] | None = None,
    thickness: int = 2,
) -> np.ndarray:
    """
    Draw a single detection on the frame.

    Args:
        frame: BGR image.
        bbox: [x1, y1, x2, y2] in pixels.
        class_name: Detection class.
        confidence: Detection confidence.
        track_id: Optional tracking ID.
        color: Override color.
        thickness: Box line thickness.

    Returns:
        Annotated frame.
    """
    if color is None:
        color = get_color(class_name)

    x1, y1, x2, y2 = [int(v) for v in bbox]
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)

    # Label text
    label_parts = []
    if track_id is not None:
        label_parts.append(f"#{track_id:02d}")
    label_parts.append(f"{class_name}")
    label_parts.append(f"{confidence:.2f}")
    label = " ".join(label_parts)

    # Label background
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.5
    (tw, th), baseline = cv2.getTextSize(label, font, font_scale, 1)
    cv2.rectangle(
        frame,
        (x1, y1 - th - baseline - 4),
        (x1 + tw + 4, y1),
        color,
        -1,
    )
    cv2.putText(
        frame, label,
        (x1 + 2, y1 - baseline - 2),
        font, font_scale, (255, 255, 255), 1, cv2.LINE_AA,
    )

    return frame


def draw_trajectory(
    frame: np.ndarray,
    center_history: list[tuple[float, float]],
    color: tuple[int, int, int] = (0, 255, 0),
    max_points: int = 30,
) -> np.ndarray:
    """Draw trajectory path from center history."""
    points = list(center_history)[-max_points:]
    if len(points) < 2:
        return frame

    for i in range(1, len(points)):
        alpha = i / len(points)
        pt1 = (int(points[i - 1][0]), int(points[i - 1][1]))
        pt2 = (int(points[i][0]), int(points[i][1]))
        thickness = max(1, int(alpha * 3))
        c = tuple(int(v * alpha) for v in color)
        cv2.line(frame, pt1, pt2, c, thickness, cv2.LINE_AA)

    return frame


def draw_status_overlay(
    frame: np.ndarray,
    track_id: int,
    bbox: list[float],
    class_name: str,
    confidence: float,
    movement_state: str = "",
    fall_detected: bool = False,
    fall_confidence: float = 0.0,
    discomfort_detected: bool = False,
    discomfort_confidence: float = 0.0,
) -> np.ndarray:
    """
    Draw a comprehensive status overlay for a tracked patient.
    Shows state, movement, fall status, and discomfort below the bbox.
    """
    x1, y1, x2, y2 = [int(v) for v in bbox]
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.4
    line_height = 16
    y_offset = y2 + 5

    info_lines = [
        f"State: {class_name} ({confidence:.2f})",
    ]
    if movement_state:
        info_lines.append(f"Movement: {movement_state}")
    if fall_detected:
        info_lines.append(f"FALL: CONFIRMED ({fall_confidence:.2f})")
    if discomfort_detected:
        info_lines.append(f"Discomfort: {discomfort_confidence:.2f}")

    for i, line in enumerate(info_lines):
        y_pos = y_offset + i * line_height
        color = (255, 255, 255)
        if "FALL" in line:
            color = FALL_ALERT_COLOR
        elif "Discomfort" in line:
            color = DISCOMFORT_ALERT_COLOR

        cv2.putText(
            frame, line,
            (x1, y_pos),
            font, font_scale, color, 1, cv2.LINE_AA,
        )

    # Fall alert banner
    if fall_detected:
        h, w = frame.shape[:2]
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (w, 35), (0, 0, 200), -1)
        cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)
        cv2.putText(
            frame,
            f"⚠ FALL DETECTED - Patient #{track_id:02d} - Confidence: {fall_confidence:.2f}",
            (10, 25),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA,
        )

    return frame


def annotate_frame(
    frame: np.ndarray,
    patient_outputs: list[dict[str, Any]],
) -> np.ndarray:
    """
    Annotate a frame with all patient detection information.

    Args:
        frame: BGR image.
        patient_outputs: List of structured patient output dicts
            (as defined in the standard output format).

    Returns:
        Annotated frame.
    """
    annotated = frame.copy()

    for patient in patient_outputs:
        bbox = patient.get("bbox", [])
        if len(bbox) < 4:
            continue

        track_id = patient.get("patient_id", 0)
        class_name = patient.get("state", "unknown")
        confidence = patient.get("confidence", 0.0)

        # Draw detection box
        annotated = draw_detection(
            annotated, bbox, class_name, confidence,
            track_id=track_id,
        )

        # Draw trajectory if available
        trajectory = patient.get("trajectory", [])
        if trajectory:
            color = get_color(class_name)
            annotated = draw_trajectory(annotated, trajectory, color)

        # Draw status overlay
        movement = patient.get("movement", {})
        fall = patient.get("fall_event", {})
        discomfort = patient.get("possible_discomfort", {})

        annotated = draw_status_overlay(
            annotated,
            track_id=track_id,
            bbox=bbox,
            class_name=class_name,
            confidence=confidence,
            movement_state=movement.get("state", ""),
            fall_detected=fall.get("detected", False),
            fall_confidence=fall.get("confidence", 0.0),
            discomfort_detected=discomfort.get("detected", False),
            discomfort_confidence=discomfort.get("confidence", 0.0),
        )

    return annotated


def save_annotated_video(
    frames: list[np.ndarray],
    output_path: Path,
    fps: float = 30.0,
) -> None:
    """Save annotated frames as a video."""
    if not frames:
        return

    h, w = frames[0].shape[:2]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(output_path), fourcc, fps, (w, h))

    for frame in frames:
        writer.write(frame)
    writer.release()
    logger.info(f"Saved annotated video to {output_path}")
