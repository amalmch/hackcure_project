"""
Evaluation Script
=================
Evaluates the trained model on validation and test splits.
Generates per-class metrics, confusion matrix, and evaluation report.

Usage:
    python scripts/evaluate.py
    python scripts/evaluate.py --model runs/patient_yolov8n/baseline/weights/best.pt
    python scripts/evaluate.py --split test
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import yaml
from ultralytics import YOLO

CV_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CV_DIR))

from src.evaluation.metrics import (
    evaluate_model,
    generate_evaluation_report,
)


def find_best_weights() -> Path | None:
    """Find the most recent best.pt in runs/."""
    runs_dir = CV_DIR / "runs" / "patient_yolov8n"
    if not runs_dir.exists():
        return None
    # Find latest experiment
    exp_dirs = sorted(
        (d for d in runs_dir.iterdir() if d.is_dir()),
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    )
    for exp_dir in exp_dirs:
        best = exp_dir / "weights" / "best.pt"
        if best.exists():
            return best
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate trained model")
    parser.add_argument(
        "--model", type=str, default=None,
        help="Path to model weights (default: auto-find best.pt)",
    )
    parser.add_argument(
        "--split", type=str, default="both",
        choices=["val", "test", "both"],
        help="Split to evaluate",
    )
    parser.add_argument(
        "--conf", type=float, default=0.001,
        help="Confidence threshold for evaluation",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger(__name__)

    # Find model
    if args.model:
        model_path = Path(args.model)
    else:
        model_path = find_best_weights()

    if model_path is None or not model_path.exists():
        logger.error(
            "No trained model found. Train first with "
            "scripts/train_patient_yolo.py"
        )
        sys.exit(1)

    logger.info(f"Model: {model_path}")

    data_yaml = CV_DIR / "data" / "processed" / "patient_detection" / "data.yaml"
    if not data_yaml.exists():
        logger.error(f"data.yaml not found: {data_yaml}")
        sys.exit(1)

    training_cfg_path = CV_DIR / "configs" / "training.yaml"
    with open(training_cfg_path, "r", encoding="utf-8") as f:
        training_cfg = yaml.safe_load(f)

    device = training_cfg["training"]["device"]
    imgsz = training_cfg["training"]["imgsz"]

    val_metrics = None
    test_metrics = None

    # Evaluate validation set
    if args.split in ("val", "both"):
        logger.info("\n" + "=" * 60)
        logger.info("VALIDATION SET EVALUATION")
        logger.info("=" * 60)
        val_metrics = evaluate_model(
            model_path=model_path,
            data_yaml=data_yaml,
            split="val",
            device=device,
            imgsz=imgsz,
            conf=args.conf,
        )
        _print_metrics(val_metrics, logger)

    # Evaluate test set
    if args.split in ("test", "both"):
        logger.info("\n" + "=" * 60)
        logger.info("TEST SET EVALUATION (Untouched)")
        logger.info("=" * 60)
        test_metrics = evaluate_model(
            model_path=model_path,
            data_yaml=data_yaml,
            split="test",
            device=device,
            imgsz=imgsz,
            conf=args.conf,
        )
        _print_metrics(test_metrics, logger)

    # Generate report
    report_path = CV_DIR / "reports" / "evaluation_report.md"
    generate_evaluation_report(
        val_metrics=val_metrics or {},
        test_metrics=test_metrics,
        fall_metrics=None,
        output_path=report_path,
    )

    # Save JSON results
    results_json = CV_DIR / "reports" / "evaluation_results.json"
    results_json.parent.mkdir(parents=True, exist_ok=True)
    with open(results_json, "w", encoding="utf-8") as f:
        json.dump(
            {"validation": val_metrics, "test": test_metrics},
            f, indent=2, default=str,
        )

    logger.info(f"\nReport: {report_path}")
    logger.info(f"JSON: {results_json}")


def _print_metrics(metrics: dict, logger: logging.Logger) -> None:
    """Print metrics summary."""
    overall = metrics.get("overall", {})
    logger.info(f"  Precision:  {overall.get('precision', 0):.4f}")
    logger.info(f"  Recall:     {overall.get('recall', 0):.4f}")
    logger.info(f"  F1:         {overall.get('f1', 0):.4f}")
    logger.info(f"  mAP@50:     {overall.get('mAP50', 0):.4f}")
    logger.info(f"  mAP@50-95:  {overall.get('mAP50_95', 0):.4f}")

    per_class = metrics.get("per_class", {})
    if per_class:
        logger.info("\n  Per-class:")
        for cls_name, m in sorted(per_class.items()):
            logger.info(
                f"    {cls_name}: P={m['precision']:.3f} "
                f"R={m['recall']:.3f} F1={m['f1']:.3f} "
                f"AP50={m['AP50']:.3f}"
            )


if __name__ == "__main__":
    main()
