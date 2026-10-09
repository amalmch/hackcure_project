"""
Error Analysis Module
=====================
Identifies and categorizes detection errors for targeted improvement.
Saves difficult examples and generates an error analysis report.
"""

import json
import logging
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import yaml
from ultralytics import YOLO

logger = logging.getLogger(__name__)


def analyze_predictions(
    model_path: Path,
    data_yaml: Path,
    split: str = "val",
    device: str | int = "0",
    imgsz: int = 640,
    conf_threshold: float = 0.25,
    low_conf_threshold: float = 0.40,
    output_dir: Path | None = None,
    max_difficult_examples: int = 50,
) -> dict[str, Any]:
    """
    Analyze detection errors on a dataset split.

    Args:
        model_path: Path to trained model weights.
        data_yaml: Path to data.yaml.
        split: Dataset split to analyze.
        device: CUDA device.
        imgsz: Image size.
        conf_threshold: Min confidence for detections.
        low_conf_threshold: Threshold below which detections are flagged.
        output_dir: Directory to save difficult examples.
        max_difficult_examples: Max number of difficult examples to save.

    Returns:
        Error analysis dictionary.
    """
    logger.info(f"Running error analysis on {split} split")
    model = YOLO(str(model_path))
    class_names = model.names

    # Load dataset info
    with open(data_yaml, "r", encoding="utf-8") as f:
        data_cfg = yaml.safe_load(f)

    dataset_root = Path(data_cfg["path"])
    images_dir = dataset_root / data_cfg.get(split, f"images/{split}")

    if not images_dir.exists():
        logger.error(f"Images directory not found: {images_dir}")
        return {"error": f"Directory not found: {images_dir}"}

    image_extensions = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
    image_files = sorted(
        f for f in images_dir.iterdir()
        if f.suffix.lower() in image_extensions
    )

    analysis = {
        "split": split,
        "total_images": len(image_files),
        "images_with_detections": 0,
        "images_without_detections": 0,
        "total_detections": 0,
        "low_confidence_detections": 0,
        "class_confusion": defaultdict(Counter),
        "detection_sizes": {"small": 0, "medium": 0, "large": 0},
        "difficult_examples": [],
        "confidence_distribution": defaultdict(int),
        "per_class_stats": defaultdict(
            lambda: {"count": 0, "avg_conf": 0.0, "low_conf": 0}
        ),
    }

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)

    difficult_saved = 0

    for img_path in image_files:
        results = model.predict(
            source=str(img_path),
            conf=conf_threshold,
            device=device,
            imgsz=imgsz,
            verbose=False,
        )

        for result in results:
            if result.boxes is None or len(result.boxes) == 0:
                analysis["images_without_detections"] += 1

                # Check if there should have been a detection (has label)
                label_path = (
                    dataset_root / f"labels/{split}" / (img_path.stem + ".txt")
                )
                if label_path.exists():
                    content = label_path.read_text(encoding="utf-8").strip()
                    if content:
                        analysis["difficult_examples"].append({
                            "image": str(img_path.name),
                            "issue": "false_negative",
                            "description": "Image has GT labels but no detections",
                        })
                        if output_dir and difficult_saved < max_difficult_examples:
                            _save_difficult(img_path, output_dir, "fn")
                            difficult_saved += 1
                continue

            analysis["images_with_detections"] += 1
            img_h, img_w = result.orig_shape

            for i in range(len(result.boxes)):
                box = result.boxes[i]
                conf = float(box.conf[0].cpu().numpy())
                cls_id = int(box.cls[0].cpu().numpy())
                cls_name = class_names.get(cls_id, f"class_{cls_id}")
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()

                analysis["total_detections"] += 1

                # Confidence distribution
                conf_bucket = int(conf * 10) / 10  # 0.0, 0.1, ..., 0.9
                analysis["confidence_distribution"][f"{conf_bucket:.1f}"] += 1

                # Per-class stats
                cls_stats = analysis["per_class_stats"][cls_name]
                cls_stats["count"] += 1
                cls_stats["avg_conf"] = (
                    (cls_stats["avg_conf"] * (cls_stats["count"] - 1) + conf)
                    / cls_stats["count"]
                )

                # Low confidence
                if conf < low_conf_threshold:
                    analysis["low_confidence_detections"] += 1
                    cls_stats["low_conf"] += 1

                    if len(analysis["difficult_examples"]) < max_difficult_examples:
                        analysis["difficult_examples"].append({
                            "image": str(img_path.name),
                            "issue": "low_confidence",
                            "class": cls_name,
                            "confidence": round(conf, 4),
                        })

                # Detection size (relative to image)
                bbox_area = ((x2 - x1) * (y2 - y1)) / (img_w * img_h)
                if bbox_area < 0.01:
                    analysis["detection_sizes"]["small"] += 1
                    if len(analysis["difficult_examples"]) < max_difficult_examples:
                        analysis["difficult_examples"].append({
                            "image": str(img_path.name),
                            "issue": "small_detection",
                            "class": cls_name,
                            "area": round(bbox_area, 6),
                        })
                elif bbox_area < 0.1:
                    analysis["detection_sizes"]["medium"] += 1
                else:
                    analysis["detection_sizes"]["large"] += 1

    # Convert defaultdicts to regular dicts for JSON
    analysis["class_confusion"] = {
        k: dict(v) for k, v in analysis["class_confusion"].items()
    }
    analysis["confidence_distribution"] = dict(
        analysis["confidence_distribution"]
    )
    analysis["per_class_stats"] = {
        k: dict(v) for k, v in analysis["per_class_stats"].items()
    }

    return analysis


def _save_difficult(
    image_path: Path,
    output_dir: Path,
    prefix: str,
) -> None:
    """Save a copy of a difficult example."""
    dest = output_dir / f"{prefix}_{image_path.name}"
    try:
        import shutil
        shutil.copy2(str(image_path), str(dest))
    except Exception as e:
        logger.warning(f"Could not save difficult example: {e}")


def generate_error_report(
    analysis: dict[str, Any],
    output_path: Path,
) -> None:
    """Generate markdown error analysis report."""
    lines = [
        "# Error Analysis Report",
        "",
        f"**Split**: {analysis.get('split', 'unknown')}",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total Images | {analysis.get('total_images', 0)} |",
        f"| Images with Detections | {analysis.get('images_with_detections', 0)} |",
        f"| Images without Detections | {analysis.get('images_without_detections', 0)} |",
        f"| Total Detections | {analysis.get('total_detections', 0)} |",
        f"| Low Confidence Detections | {analysis.get('low_confidence_detections', 0)} |",
        "",
        "## Detection Sizes",
        "",
        "| Size | Count |",
        "|------|-------|",
    ]

    for size, count in analysis.get("detection_sizes", {}).items():
        lines.append(f"| {size} | {count} |")
    lines.append("")

    # Per-class stats
    lines.extend([
        "## Per-Class Statistics",
        "",
        "| Class | Count | Avg Confidence | Low Confidence |",
        "|-------|-------|----------------|----------------|",
    ])
    for cls_name, stats in sorted(
        analysis.get("per_class_stats", {}).items()
    ):
        lines.append(
            f"| {cls_name} | {stats.get('count', 0)} "
            f"| {stats.get('avg_conf', 0):.4f} "
            f"| {stats.get('low_conf', 0)} |"
        )
    lines.append("")

    # Confidence distribution
    lines.extend([
        "## Confidence Distribution",
        "",
        "| Bucket | Count |",
        "|--------|-------|",
    ])
    for bucket, count in sorted(
        analysis.get("confidence_distribution", {}).items()
    ):
        lines.append(f"| {bucket} | {count} |")
    lines.append("")

    # Difficult examples
    difficult = analysis.get("difficult_examples", [])
    if difficult:
        lines.extend([
            "## Difficult Examples (first 30)",
            "",
            "| Image | Issue | Details |",
            "|-------|-------|---------|",
        ])
        for ex in difficult[:30]:
            details = ", ".join(
                f"{k}={v}" for k, v in ex.items()
                if k not in ("image", "issue")
            )
            lines.append(
                f"| {ex.get('image', '')} | {ex.get('issue', '')} "
                f"| {details} |"
            )
        lines.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    logger.info(f"Error analysis report saved to {output_path}")
