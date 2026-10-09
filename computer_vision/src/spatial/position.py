"""
Spatial Position Module
=======================
Provides normalized image coordinates and pixel coordinates
for patient bounding boxes. These coordinates will later be
mapped by the larger project to room zones (bed, floor, etc.).
"""

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PatientPosition:
    """Spatial position derived from a bounding box."""

    # Normalized coordinates (0-1)
    x_center: float = 0.0
    y_center: float = 0.0
    bottom_x: float = 0.0
    bottom_y: float = 0.0

    # Pixel coordinates
    x_center_px: int = 0
    y_center_px: int = 0
    bottom_x_px: int = 0
    bottom_y_px: int = 0

    # Bounding box area (normalized)
    area_norm: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for structured output."""
        return {
            "x_center": round(self.x_center, 4),
            "y_center": round(self.y_center, 4),
            "bottom_x": round(self.bottom_x, 4),
            "bottom_y": round(self.bottom_y, 4),
            "x_center_px": self.x_center_px,
            "y_center_px": self.y_center_px,
            "bottom_x_px": self.bottom_x_px,
            "bottom_y_px": self.bottom_y_px,
            "area_norm": round(self.area_norm, 6),
        }


def compute_position(
    bbox: list[float],
    image_width: int,
    image_height: int,
) -> PatientPosition:
    """
    Compute patient position from bounding box.

    Args:
        bbox: [x1, y1, x2, y2] in pixel coordinates.
        image_width: Image width in pixels.
        image_height: Image height in pixels.

    Returns:
        PatientPosition with normalized and pixel coordinates.
    """
    if len(bbox) < 4 or image_width <= 0 or image_height <= 0:
        return PatientPosition()

    x1, y1, x2, y2 = bbox

    # Center
    cx_px = int((x1 + x2) / 2)
    cy_px = int((y1 + y2) / 2)

    # Bottom center (feet position - most relevant for floor contact)
    bx_px = int((x1 + x2) / 2)
    by_px = int(y2)

    # Normalized
    cx_norm = (x1 + x2) / 2 / image_width
    cy_norm = (y1 + y2) / 2 / image_height
    bx_norm = (x1 + x2) / 2 / image_width
    by_norm = y2 / image_height

    # Area
    w_norm = (x2 - x1) / image_width
    h_norm = (y2 - y1) / image_height
    area = w_norm * h_norm

    return PatientPosition(
        x_center=cx_norm,
        y_center=cy_norm,
        bottom_x=bx_norm,
        bottom_y=by_norm,
        x_center_px=cx_px,
        y_center_px=cy_px,
        bottom_x_px=bx_px,
        bottom_y_px=by_px,
        area_norm=area,
    )
