"""
Dataset Harmonization Module
=============================
Converts annotations from different source formats into a unified
YOLO detection format using the canonical class mapping.

Handles:
- YOLO segmentation polygons → YOLO detection bboxes
- YOLO detection bboxes → remapped class IDs
- Class filtering (EXCLUDE/REMAP/KEEP)
"""

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def load_config(config_path: Path) -> dict:
    """Load a YAML configuration file."""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_class_remap_table(
    mapping_config: list[dict],
) -> dict[int, dict[str, Any]]:
    """
    Build a lookup table from source class ID to mapping info.

    Returns:
        Dict mapping source_class_id to:
        {
            "action": "KEEP" | "REMAP" | "EXCLUDE",
            "canonical_class": str | None,
            "canonical_class_id": int | None,
            "reason": str,
        }
    """
    table = {}
    for entry in mapping_config:
        src_id = entry["source_class_id"]
        if src_id is not None:
            table[src_id] = {
                "action": entry["action"],
                "canonical_class": entry.get("canonical_class"),
                "canonical_class_id": entry.get("canonical_class_id"),
                "reason": entry.get("reason", ""),
            }
    return table


def polygon_to_bbox(polygon_values: list[float]) -> tuple[float, float, float, float]:
    """
    Convert a list of polygon coordinates [x1, y1, x2, y2, ...]
    to a YOLO detection bbox [x_center, y_center, width, height].

    All values are normalized (0-1).
    """
    xs = polygon_values[0::2]
    ys = polygon_values[1::2]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    x_center = (x_min + x_max) / 2.0
    y_center = (y_min + y_max) / 2.0
    width = x_max - x_min
    height = y_max - y_min
    return x_center, y_center, width, height


def harmonize_label_line(
    line: str,
    remap_table: dict[int, dict[str, Any]],
    source_format: str,
) -> tuple[str | None, dict[str, Any]]:
    """
    Convert a single label line to canonical YOLO detection format.

    Args:
        line: Raw label line from source dataset.
        remap_table: Class remapping table.
        source_format: "yolov8_detect" or "yolov8_segment".

    Returns:
        Tuple of (converted_line or None, info_dict).
        converted_line is None if the annotation should be excluded.
    """
    parts = line.strip().split()
    if len(parts) < 5:
        return None, {"action": "SKIP", "reason": "Malformed line"}

    try:
        src_class_id = int(parts[0])
    except ValueError:
        return None, {"action": "SKIP", "reason": f"Invalid class ID: {parts[0]}"}

    # Check mapping
    mapping = remap_table.get(src_class_id)
    if mapping is None:
        return None, {
            "action": "EXCLUDE",
            "reason": f"Class ID {src_class_id} not in mapping table",
        }

    if mapping["action"] == "EXCLUDE":
        return None, {
            "action": "EXCLUDE",
            "reason": mapping["reason"],
            "source_class_id": src_class_id,
        }

    new_class_id = mapping["canonical_class_id"]
    if new_class_id is None:
        return None, {
            "action": "EXCLUDE",
            "reason": "No canonical class ID assigned",
        }

    # Parse coordinates
    try:
        values = [float(v) for v in parts[1:]]
    except ValueError:
        return None, {"action": "SKIP", "reason": "Non-numeric coordinates"}

    num_values = len(values)

    if source_format == "yolov8_segment" or num_values > 4:
        # Polygon format → convert to bbox
        if num_values >= 6 and num_values % 2 == 0:
            x_c, y_c, w, h = polygon_to_bbox(values)
        elif num_values == 4:
            x_c, y_c, w, h = values
        else:
            return None, {
                "action": "SKIP",
                "reason": f"Unexpected coordinate count: {num_values}",
            }
    else:
        # Already detection format
        x_c, y_c, w, h = values[:4]

    # Validate bbox
    if w <= 0 or h <= 0:
        return None, {"action": "SKIP", "reason": "Zero-area bbox"}

    # Clamp to valid range
    x_c = max(0.0, min(1.0, x_c))
    y_c = max(0.0, min(1.0, y_c))
    w = max(0.001, min(1.0, w))
    h = max(0.001, min(1.0, h))

    converted_line = f"{new_class_id} {x_c:.6f} {y_c:.6f} {w:.6f} {h:.6f}"

    info = {
        "action": mapping["action"],
        "source_class_id": src_class_id,
        "canonical_class_id": new_class_id,
        "canonical_class": mapping["canonical_class"],
        "bbox": [x_c, y_c, w, h],
    }
    return converted_line, info


def harmonize_label_file(
    label_path: Path,
    remap_table: dict[int, dict[str, Any]],
    source_format: str,
) -> tuple[list[str], list[dict[str, Any]]]:
    """
    Harmonize an entire label file.

    Returns:
        Tuple of (list of converted lines, list of info dicts per annotation).
    """
    converted_lines = []
    infos = []

    if not label_path.exists():
        return converted_lines, infos

    with open(label_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            converted, info = harmonize_label_line(
                line, remap_table, source_format
            )
            infos.append(info)
            if converted is not None:
                converted_lines.append(converted)

    return converted_lines, infos


def get_remap_tables(cv_dir: Path) -> dict[str, dict[int, dict[str, Any]]]:
    """
    Load the dataset config and build remap tables for each dataset.

    Returns:
        Dict mapping dataset key to its remap table.
    """
    config = load_config(cv_dir / "configs" / "datasets.yaml")
    tables = {}

    for ds_key, mappings in config["class_mapping"].items():
        if isinstance(mappings, list):
            tables[ds_key] = build_class_remap_table(mappings)
        else:
            tables[ds_key] = {}

    return tables
