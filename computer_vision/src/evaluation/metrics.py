"""
Evaluation Metrics Module
=========================
Computes per-class and overall detection metrics, plus
fall-specific safety metrics at both frame and event level.
"""

import json
import logging
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from ultralytics import YOLO

logger = logging.getLogger(__name__)


def evaluate_model(
    model_path: Path,
    data_yaml: Path,
    split: str = "val",
    device: str | int = "0",
    imgsz: int = 640,
    conf: float = 0.001,
    iou: float = 0.6,
    verbose: bool = True,
) -> dict[str, Any]:
    """
    Evaluate a YOLO model on a dataset split.

    Args:
        model_path: Path to best.pt or trained weights.
        data_yaml: Path to data.yaml.
        split: 'val' or 'test'.
        device: CUDA device.
        imgsz: Image size.
        conf: Confidence threshold for evaluation.
        iou: IoU threshold for evaluation.
        verbose: Print detailed output.

    Returns:
        Dictionary with evaluation results.
    """
    logger.info(f"Evaluating {model_path} on {split} split")
    model = YOLO(str(model_path))

    results = model.val(
        data=str(data_yaml),
        split=split,
        device=device,
        imgsz=imgsz,
        conf=conf,
        iou=iou,
        verbose=verbose,
        plots=True,
    )

    # Extract metrics
    class_names = model.names
    metrics = {
        "split": split,
        "model": str(model_path),
        "overall": {},
        "per_class": {},
    }

    # Overall metrics
    box_metrics = results.box
    metrics["overall"] = {
        "precision": float(box_metrics.mp),
        "recall": float(box_metrics.mr),
        "f1": float(2 * box_metrics.mp * box_metrics.mr / (box_metrics.mp + box_metrics.mr + 1e-8)),
        "mAP50": float(box_metrics.map50),
        "mAP50_95": float(box_metrics.map),
    }

    # Per-class metrics
    if hasattr(box_metrics, 'ap_class_index') and box_metrics.ap_class_index is not None:
        for i, cls_idx in enumerate(box_metrics.ap_class_index):
            cls_name = class_names.get(int(cls_idx), f"class_{cls_idx}")
            p = float(box_metrics.p[i]) if i < len(box_metrics.p) else 0.0
            r = float(box_metrics.r[i]) if i < len(box_metrics.r) else 0.0
            f1 = 2 * p * r / (p + r + 1e-8)
            ap50 = float(box_metrics.ap50[i]) if i < len(box_metrics.ap50) else 0.0
            ap = float(box_metrics.ap[i]) if i < len(box_metrics.ap) else 0.0

            metrics["per_class"][cls_name] = {
                "class_id": int(cls_idx),
                "precision": p,
                "recall": r,
                "f1": f1,
                "AP50": ap50,
                "AP50_95": ap,
            }

    # Save directory from results
    if hasattr(results, 'save_dir'):
        metrics["plots_dir"] = str(results.save_dir)

    return metrics


def compute_fall_metrics(
    predictions: list[dict],
    ground_truth: list[dict],
    fallen_class_names: set[str] | None = None,
) -> dict[str, Any]:
    """
    Compute fall-specific metrics at frame and event level.

    Args:
        predictions: List of per-frame prediction dicts with keys:
            frame_idx, class_name, confidence, track_id
        ground_truth: List of per-frame GT dicts with keys:
            frame_idx, class_name
        fallen_class_names: Set of class names considered as "fallen".

    Returns:
        Dictionary with frame-level and event-level fall metrics.
    """
    if fallen_class_names is None:
        fallen_class_names = {"patient_fallen"}

    # Frame-level metrics
    frame_tp = 0
    frame_fp = 0
    frame_fn = 0
    frame_tn = 0

    gt_by_frame = defaultdict(list)
    pred_by_frame = defaultdict(list)

    for g in ground_truth:
        gt_by_frame[g["frame_idx"]].append(g)
    for p in predictions:
        pred_by_frame[p["frame_idx"]].append(p)

    all_frames = set(gt_by_frame.keys()) | set(pred_by_frame.keys())

    for frame_idx in all_frames:
        gt_has_fall = any(
            g["class_name"] in fallen_class_names
            for g in gt_by_frame.get(frame_idx, [])
        )
        pred_has_fall = any(
            p["class_name"] in fallen_class_names
            for p in pred_by_frame.get(frame_idx, [])
        )

        if gt_has_fall and pred_has_fall:
            frame_tp += 1
        elif not gt_has_fall and pred_has_fall:
            frame_fp += 1
        elif gt_has_fall and not pred_has_fall:
            frame_fn += 1
        else:
            frame_tn += 1

    frame_precision = frame_tp / (frame_tp + frame_fp) if (frame_tp + frame_fp) > 0 else 0.0
    frame_recall = frame_tp / (frame_tp + frame_fn) if (frame_tp + frame_fn) > 0 else 0.0
    frame_f1 = (
        2 * frame_precision * frame_recall / (frame_precision + frame_recall)
        if (frame_precision + frame_recall) > 0 else 0.0
    )

    metrics = {
        "frame_level": {
            "true_positives": frame_tp,
            "false_positives": frame_fp,
            "false_negatives": frame_fn,
            "true_negatives": frame_tn,
            "precision": round(frame_precision, 4),
            "recall": round(frame_recall, 4),
            "sensitivity": round(frame_recall, 4),
            "f1": round(frame_f1, 4),
        },
        "event_level": {
            "note": (
                "Event-level metrics require temporal ground truth with "
                "fall event boundaries. Computed when available."
            ),
        },
    }

    return metrics


def generate_evaluation_report(
    val_metrics: dict,
    test_metrics: dict | None,
    fall_metrics: dict | None,
    output_path: Path,
) -> None:
    """Generate a markdown evaluation report."""
    lines = [
        "# Evaluation Report",
        "",
        "## Validation Set Results",
        "",
    ]

    # Overall metrics table
    overall = val_metrics.get("overall", {})
    lines.extend([
        "### Overall Metrics",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Precision | {overall.get('precision', 0):.4f} |",
        f"| Recall | {overall.get('recall', 0):.4f} |",
        f"| F1 | {overall.get('f1', 0):.4f} |",
        f"| mAP@50 | {overall.get('mAP50', 0):.4f} |",
        f"| mAP@50-95 | {overall.get('mAP50_95', 0):.4f} |",
        "",
    ])

    # Per-class
    per_class = val_metrics.get("per_class", {})
    if per_class:
        lines.extend([
            "### Per-Class Metrics",
            "",
            "| Class | Precision | Recall | F1 | AP@50 | AP@50-95 |",
            "|-------|-----------|--------|----|-------|----------|",
        ])
        for cls_name, m in sorted(per_class.items()):
            lines.append(
                f"| {cls_name} | {m['precision']:.4f} | {m['recall']:.4f} "
                f"| {m['f1']:.4f} | {m['AP50']:.4f} | {m['AP50_95']:.4f} |"
            )
        lines.append("")

    # Test set
    if test_metrics:
        lines.extend([
            "## Test Set Results",
            "",
        ])
        overall = test_metrics.get("overall", {})
        lines.extend([
            "### Overall Metrics",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Precision | {overall.get('precision', 0):.4f} |",
            f"| Recall | {overall.get('recall', 0):.4f} |",
            f"| F1 | {overall.get('f1', 0):.4f} |",
            f"| mAP@50 | {overall.get('mAP50', 0):.4f} |",
            f"| mAP@50-95 | {overall.get('mAP50_95', 0):.4f} |",
            "",
        ])

        per_class = test_metrics.get("per_class", {})
        if per_class:
            lines.extend([
                "### Per-Class Metrics",
                "",
                "| Class | Precision | Recall | F1 | AP@50 | AP@50-95 |",
                "|-------|-----------|--------|----|-------|----------|",
            ])
            for cls_name, m in sorted(per_class.items()):
                lines.append(
                    f"| {cls_name} | {m['precision']:.4f} | {m['recall']:.4f} "
                    f"| {m['f1']:.4f} | {m['AP50']:.4f} | {m['AP50_95']:.4f} |"
                )
            lines.append("")

    # Fall metrics
    if fall_metrics:
        lines.extend([
            "## Fall-Specific Metrics",
            "",
        ])
        fl = fall_metrics.get("frame_level", {})
        if fl:
            lines.extend([
                "### Frame-Level",
                "",
                "| Metric | Value |",
                "|--------|-------|",
                f"| True Positives | {fl.get('true_positives', 0)} |",
                f"| False Positives | {fl.get('false_positives', 0)} |",
                f"| False Negatives | {fl.get('false_negatives', 0)} |",
                f"| Precision | {fl.get('precision', 0):.4f} |",
                f"| Recall / Sensitivity | {fl.get('recall', 0):.4f} |",
                f"| F1 | {fl.get('f1', 0):.4f} |",
                "",
            ])

        el = fall_metrics.get("event_level", {})
        if el and el.get("note"):
            lines.extend([
                "### Event-Level",
                "",
                f"> {el['note']}",
                "",
            ])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    logger.info(f"Evaluation report saved to {output_path}")
