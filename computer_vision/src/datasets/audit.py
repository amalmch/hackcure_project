"""
Dataset Audit Module
====================
Inspects all three local datasets and produces detailed audit reports.
Determines annotation format, class distribution, and data quality metrics.
"""

import hashlib
import json
import logging
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import yaml

logger = logging.getLogger(__name__)


def load_config(config_path: Path) -> dict:
    """Load a YAML configuration file."""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve_project_root(cv_dir: Path) -> Path:
    """Resolve the project root from the computer_vision directory."""
    return cv_dir.parent


def compute_file_hash(filepath: Path, algorithm: str = "md5") -> str:
    """Compute hash of a file for deduplication."""
    h = hashlib.new(algorithm)
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def get_image_resolution(image_path: Path) -> tuple[int, int] | None:
    """Get image width and height using OpenCV."""
    try:
        img = cv2.imread(str(image_path))
        if img is not None:
            h, w = img.shape[:2]
            return w, h
    except Exception as e:
        logger.warning(f"Could not read image {image_path}: {e}")
    return None


def parse_yolo_label(label_path: Path) -> list[dict]:
    """
    Parse a YOLO label file.
    Handles both detection (5 values) and segmentation (polygon) formats.
    Returns list of annotation dicts.
    """
    annotations = []
    if not label_path.exists():
        return annotations

    try:
        with open(label_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) < 5:
                    annotations.append({
                        "line_num": line_num,
                        "valid": False,
                        "error": f"Too few values ({len(parts)})",
                        "raw": line,
                    })
                    continue

                try:
                    class_id = int(parts[0])
                except ValueError:
                    annotations.append({
                        "line_num": line_num,
                        "valid": False,
                        "error": f"Non-integer class ID: {parts[0]}",
                        "raw": line,
                    })
                    continue

                values = []
                valid = True
                error = None
                for v in parts[1:]:
                    try:
                        values.append(float(v))
                    except ValueError:
                        valid = False
                        error = f"Non-numeric value: {v}"
                        break

                if not valid:
                    annotations.append({
                        "line_num": line_num,
                        "valid": False,
                        "error": error,
                        "raw": line,
                    })
                    continue

                num_coords = len(values)
                if num_coords == 4:
                    # Standard detection: class x_center y_center width height
                    ann_format = "detect"
                    x_c, y_c, w, h = values
                    bbox_valid = (
                        0 <= x_c <= 1 and 0 <= y_c <= 1
                        and 0 < w <= 1 and 0 < h <= 1
                    )
                    annotations.append({
                        "line_num": line_num,
                        "valid": bbox_valid,
                        "class_id": class_id,
                        "format": ann_format,
                        "bbox": [x_c, y_c, w, h],
                        "error": None if bbox_valid else "Values out of valid range",
                        "raw": line,
                    })
                elif num_coords >= 6 and num_coords % 2 == 0:
                    # Segmentation polygon: class x1 y1 x2 y2 ...
                    ann_format = "segment"
                    # Convert polygon to bounding box
                    xs = values[0::2]
                    ys = values[1::2]
                    x_min, x_max = min(xs), max(xs)
                    y_min, y_max = min(ys), max(ys)
                    x_c = (x_min + x_max) / 2
                    y_c = (y_min + y_max) / 2
                    w = x_max - x_min
                    h = y_max - y_min
                    bbox_valid = w > 0 and h > 0
                    annotations.append({
                        "line_num": line_num,
                        "valid": bbox_valid,
                        "class_id": class_id,
                        "format": ann_format,
                        "polygon_points": len(xs),
                        "bbox": [x_c, y_c, w, h],
                        "error": None if bbox_valid else "Degenerate polygon",
                        "raw": line,
                    })
                else:
                    annotations.append({
                        "line_num": line_num,
                        "valid": False,
                        "class_id": class_id,
                        "format": "unknown",
                        "error": f"Unexpected number of coordinates: {num_coords}",
                        "raw": line,
                    })
    except Exception as e:
        logger.error(f"Error reading label file {label_path}: {e}")
    return annotations


def audit_yolo_dataset(
    dataset_name: str,
    dataset_path: Path,
    class_names: dict[int, str],
    splits: dict[str, str],
    annotation_format: str,
) -> dict[str, Any]:
    """
    Audit a YOLO-format dataset (detection or segmentation).

    Returns a comprehensive audit dictionary.
    """
    audit = {
        "name": dataset_name,
        "path": str(dataset_path),
        "annotation_format": annotation_format,
        "class_names": class_names,
        "splits": {},
        "totals": {
            "images": 0,
            "labels": 0,
            "bboxes": 0,
            "missing_labels": 0,
            "missing_images": 0,
            "empty_labels": 0,
            "malformed_labels": 0,
        },
        "class_distribution": Counter(),
        "resolutions": Counter(),
        "errors": [],
    }

    image_hashes: dict[str, list[str]] = defaultdict(list)

    for split_name, split_dir in splits.items():
        split_path = dataset_path / split_dir
        images_dir = split_path / "images"
        labels_dir = split_path / "labels"

        split_info = {
            "images": 0,
            "labels": 0,
            "bboxes": 0,
            "missing_labels": 0,
            "missing_images": 0,
            "empty_labels": 0,
            "malformed_lines": 0,
            "class_distribution": Counter(),
            "resolutions": [],
        }

        if not images_dir.exists():
            audit["errors"].append(f"Images directory not found: {images_dir}")
            audit["splits"][split_name] = split_info
            continue

        image_extensions = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
        image_files = sorted(
            f for f in images_dir.iterdir()
            if f.suffix.lower() in image_extensions
        )
        split_info["images"] = len(image_files)

        for img_file in image_files:
            # Check resolution for a sample
            if len(split_info["resolutions"]) < 50:
                res = get_image_resolution(img_file)
                if res:
                    split_info["resolutions"].append(res)
                    audit["resolutions"][f"{res[0]}x{res[1]}"] += 1

            # Compute hash for deduplication
            img_hash = compute_file_hash(img_file)
            image_hashes[img_hash].append(str(img_file))

            # Check for corresponding label
            label_file = labels_dir / (img_file.stem + ".txt")
            if not label_file.exists():
                split_info["missing_labels"] += 1
                continue

            split_info["labels"] += 1
            annotations = parse_yolo_label(label_file)

            if not annotations:
                split_info["empty_labels"] += 1
                continue

            for ann in annotations:
                if ann["valid"]:
                    split_info["bboxes"] += 1
                    cid = ann["class_id"]
                    split_info["class_distribution"][cid] += 1
                    audit["class_distribution"][cid] += 1
                else:
                    split_info["malformed_lines"] += 1
                    audit["errors"].append(
                        f"Malformed label in {label_file.name} "
                        f"line {ann.get('line_num', '?')}: {ann.get('error', 'unknown')}"
                    )

        # Check for labels without corresponding images
        if labels_dir.exists():
            label_files = sorted(
                f for f in labels_dir.iterdir() if f.suffix == ".txt"
            )
            for lbl_file in label_files:
                has_image = any(
                    (images_dir / (lbl_file.stem + ext)).exists()
                    for ext in image_extensions
                )
                if not has_image:
                    split_info["missing_images"] += 1

        # Update totals
        audit["totals"]["images"] += split_info["images"]
        audit["totals"]["labels"] += split_info["labels"]
        audit["totals"]["bboxes"] += split_info["bboxes"]
        audit["totals"]["missing_labels"] += split_info["missing_labels"]
        audit["totals"]["missing_images"] += split_info["missing_images"]
        audit["totals"]["empty_labels"] += split_info["empty_labels"]
        audit["totals"]["malformed_labels"] += split_info["malformed_lines"]

        # Convert Counter to dict for JSON serialization
        split_info["class_distribution"] = dict(split_info["class_distribution"])
        audit["splits"][split_name] = split_info

    # Find duplicates
    duplicates = {h: paths for h, paths in image_hashes.items() if len(paths) > 1}
    audit["duplicate_images"] = len(duplicates)
    audit["duplicate_details"] = {
        h: paths for h, paths in list(duplicates.items())[:20]
    }

    # Convert Counters to dicts
    audit["class_distribution"] = dict(audit["class_distribution"])
    audit["resolutions"] = dict(audit["resolutions"])

    # Calculate class imbalance
    if audit["class_distribution"]:
        counts = list(audit["class_distribution"].values())
        max_count = max(counts)
        min_count = min(counts)
        audit["class_imbalance_ratio"] = (
            round(max_count / min_count, 2) if min_count > 0 else float("inf")
        )
    else:
        audit["class_imbalance_ratio"] = None

    return audit


def audit_gmdcsa_dataset(dataset_path: Path) -> dict[str, Any]:
    """
    Audit the GMDCSA-24 video dataset.
    This dataset has no YOLO annotations - only videos with CSV temporal labels.
    """
    audit = {
        "name": "GMDCSA-24",
        "path": str(dataset_path),
        "annotation_format": "video_csv",
        "type": "video_temporal",
        "subjects": {},
        "totals": {
            "videos": 0,
            "adl_videos": 0,
            "fall_videos": 0,
            "total_subjects": 0,
        },
        "temporal_classes": set(),
        "note": (
            "Video-only dataset with temporal CSV annotations. "
            "No YOLO bounding-box labels available. "
            "Not directly usable for YOLO training without manual annotation."
        ),
    }

    subjects = sorted(
        d for d in dataset_path.iterdir()
        if d.is_dir() and d.name.startswith("Subject")
    )
    audit["totals"]["total_subjects"] = len(subjects)

    for subject_dir in subjects:
        subject_info = {"adl_videos": 0, "fall_videos": 0, "classes": set()}

        for category in ["ADL", "Fall"]:
            video_dir = subject_dir / category
            csv_file = subject_dir / f"{category}.csv"

            if video_dir.exists():
                videos = [
                    f for f in video_dir.iterdir()
                    if f.suffix.lower() in {".mp4", ".avi", ".mov", ".mkv"}
                ]
                count = len(videos)
                if category == "ADL":
                    subject_info["adl_videos"] = count
                    audit["totals"]["adl_videos"] += count
                else:
                    subject_info["fall_videos"] = count
                    audit["totals"]["fall_videos"] += count
                audit["totals"]["videos"] += count

            # Parse CSV for temporal classes
            if csv_file.exists():
                try:
                    import csv
                    with open(csv_file, "r", encoding="utf-8") as f:
                        reader = csv.reader(f)
                        header = next(reader, None)
                        for row in reader:
                            if len(row) >= 6:
                                classes_str = row[5].strip()
                                # Extract class names like "Sitting[0 to 1]"
                                import re
                                class_names_found = re.findall(
                                    r"([A-Za-z\s\(\)]+)\[",
                                    classes_str,
                                )
                                for cn in class_names_found:
                                    cn = cn.strip()
                                    if cn:
                                        subject_info["classes"].add(cn)
                                        audit["temporal_classes"].add(cn)
                except Exception as e:
                    logger.warning(
                        f"Error parsing {csv_file}: {e}"
                    )

        subject_info["classes"] = sorted(subject_info["classes"])
        audit["subjects"][subject_dir.name] = subject_info

    audit["temporal_classes"] = sorted(audit["temporal_classes"])
    return audit


def generate_audit_report(
    audits: list[dict[str, Any]],
    output_md: Path,
    output_json: Path,
) -> None:
    """Generate markdown and JSON audit reports."""

    # JSON report
    json_data = {}
    for audit in audits:
        json_data[audit["name"]] = audit

    output_json.parent.mkdir(parents=True, exist_ok=True)
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=2, default=str)
    logger.info(f"JSON audit saved to {output_json}")

    # Markdown report
    output_md.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Dataset Audit Report",
        "",
        f"Generated automatically by the dataset audit pipeline.",
        "",
    ]

    for audit in audits:
        lines.append(f"## {audit['name']}")
        lines.append("")
        lines.append(f"- **Path**: `{audit['path']}`")
        lines.append(f"- **Annotation Format**: `{audit['annotation_format']}`")
        lines.append("")

        if audit["annotation_format"] == "video_csv":
            totals = audit["totals"]
            lines.append(f"- **Subjects**: {totals['total_subjects']}")
            lines.append(f"- **Total Videos**: {totals['videos']}")
            lines.append(f"- **ADL Videos**: {totals['adl_videos']}")
            lines.append(f"- **Fall Videos**: {totals['fall_videos']}")
            lines.append("")
            lines.append("### Temporal Classes Found")
            lines.append("")
            for cls in audit.get("temporal_classes", []):
                lines.append(f"- {cls}")
            lines.append("")
            lines.append(f"> **Note**: {audit.get('note', '')}")
            lines.append("")

            for subj, info in audit.get("subjects", {}).items():
                lines.append(f"#### {subj}")
                lines.append(f"- ADL videos: {info['adl_videos']}")
                lines.append(f"- Fall videos: {info['fall_videos']}")
                lines.append(f"- Classes: {', '.join(info['classes'])}")
                lines.append("")
        else:
            totals = audit["totals"]
            lines.append("### Summary")
            lines.append("")
            lines.append(f"| Metric | Count |")
            lines.append(f"|--------|-------|")
            lines.append(f"| Total Images | {totals['images']} |")
            lines.append(f"| Total Labels | {totals['labels']} |")
            lines.append(f"| Total Bounding Boxes | {totals['bboxes']} |")
            lines.append(f"| Missing Labels | {totals['missing_labels']} |")
            lines.append(f"| Missing Images | {totals['missing_images']} |")
            lines.append(f"| Empty Labels | {totals['empty_labels']} |")
            lines.append(f"| Malformed Labels | {totals['malformed_labels']} |")
            lines.append(f"| Duplicate Images | {audit.get('duplicate_images', 0)} |")
            lines.append(
                f"| Class Imbalance Ratio | "
                f"{audit.get('class_imbalance_ratio', 'N/A')} |"
            )
            lines.append("")

            # Class names
            lines.append("### Classes")
            lines.append("")
            lines.append("| ID | Name |")
            lines.append("|----|------|")
            for cid, cname in sorted(audit["class_names"].items()):
                lines.append(f"| {cid} | {cname} |")
            lines.append("")

            # Class distribution
            lines.append("### Class Distribution")
            lines.append("")
            lines.append("| Class ID | Class Name | Count |")
            lines.append("|----------|-----------|-------|")
            for cid, count in sorted(audit["class_distribution"].items()):
                cname = audit["class_names"].get(int(cid), "unknown")
                lines.append(f"| {cid} | {cname} | {count} |")
            lines.append("")

            # Per-split details
            lines.append("### Per-Split Details")
            lines.append("")
            for split_name, split_info in audit["splits"].items():
                lines.append(f"#### {split_name}")
                lines.append(f"- Images: {split_info['images']}")
                lines.append(f"- Labels: {split_info['labels']}")
                lines.append(f"- Bboxes: {split_info['bboxes']}")
                lines.append(
                    f"- Missing labels: {split_info['missing_labels']}"
                )
                lines.append(
                    f"- Empty labels: {split_info['empty_labels']}"
                )
                lines.append("")

            # Resolutions
            if audit.get("resolutions"):
                lines.append("### Image Resolutions")
                lines.append("")
                lines.append("| Resolution | Count |")
                lines.append("|-----------|-------|")
                for res, count in sorted(
                    audit["resolutions"].items(),
                    key=lambda x: x[1],
                    reverse=True,
                ):
                    lines.append(f"| {res} | {count} |")
                lines.append("")

            # Errors (first 20)
            errors = audit.get("errors", [])
            if errors:
                lines.append("### Errors (first 20)")
                lines.append("")
                for err in errors[:20]:
                    lines.append(f"- {err}")
                if len(errors) > 20:
                    lines.append(f"- ... and {len(errors) - 20} more")
                lines.append("")

        lines.append("---")
        lines.append("")

    # Class mapping table
    lines.append("## Canonical Class Mapping")
    lines.append("")
    lines.append(
        "| Source Dataset | Source Class | Source ID "
        "| Canonical Class | Action | Reason |"
    )
    lines.append("|---------------|------------|-----------|"
                 "----------------|--------|--------|")

    with open(output_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.info(f"Markdown audit saved to {output_md}")


def run_full_audit(cv_dir: Path) -> list[dict[str, Any]]:
    """
    Run a full audit of all three datasets.

    Args:
        cv_dir: Path to the computer_vision/ directory.

    Returns:
        List of audit dictionaries.
    """
    config_path = cv_dir / "configs" / "datasets.yaml"
    config = load_config(config_path)
    project_root = resolve_project_root(cv_dir)

    audits = []

    # Audit TCC Person Fall
    ds_config = config["datasets"]["tcc_person_fall"]
    ds_path = project_root / ds_config["path"]
    logger.info(f"Auditing {ds_config['name']} at {ds_path}")
    audit = audit_yolo_dataset(
        dataset_name=ds_config["name"],
        dataset_path=ds_path,
        class_names={int(k): v for k, v in ds_config["original_classes"].items()},
        splits=ds_config["splits"],
        annotation_format=ds_config["format"],
    )
    audits.append(audit)

    # Audit Human Fall v2
    ds_config = config["datasets"]["human_fall_v2"]
    ds_path = project_root / ds_config["path"]
    logger.info(f"Auditing {ds_config['name']} at {ds_path}")
    audit = audit_yolo_dataset(
        dataset_name=ds_config["name"],
        dataset_path=ds_path,
        class_names={int(k): v for k, v in ds_config["original_classes"].items()},
        splits=ds_config["splits"],
        annotation_format=ds_config["format"],
    )
    audits.append(audit)

    # Audit GMDCSA-24
    ds_config = config["datasets"]["gmdcsa24"]
    ds_path = project_root / ds_config["path"]
    logger.info(f"Auditing {ds_config['name']} at {ds_path}")
    audit = audit_gmdcsa_dataset(ds_path)
    audits.append(audit)

    # Generate reports
    output_md = cv_dir / "reports" / "dataset_audit.md"
    output_json = cv_dir / "data" / "manifests" / "dataset_audit.json"
    generate_audit_report(audits, output_md, output_json)

    return audits
