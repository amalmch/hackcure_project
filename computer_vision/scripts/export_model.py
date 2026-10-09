"""
Model Export Script
===================
Exports the trained YOLOv8n model for future deployment.

Usage:
    python scripts/export_model.py
    python scripts/export_model.py --model runs/patient_yolov8n/baseline/weights/best.pt
    python scripts/export_model.py --format onnx
"""

import argparse
import logging
import shutil
import sys
from pathlib import Path

from ultralytics import YOLO

CV_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CV_DIR))


def find_best_weights() -> Path | None:
    """Find the most recent best.pt."""
    runs_dir = CV_DIR / "runs" / "patient_yolov8n"
    if not runs_dir.exists():
        return None
    for exp_dir in sorted(
        runs_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True
    ):
        if exp_dir.is_dir():
            best = exp_dir / "weights" / "best.pt"
            if best.exists():
                return best
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Export trained YOLOv8n model")
    parser.add_argument(
        "--model", type=str, default=None,
        help="Path to model weights",
    )
    parser.add_argument(
        "--format", type=str, default="onnx",
        choices=["onnx", "torchscript", "openvino", "engine", "tflite"],
        help="Export format",
    )
    parser.add_argument(
        "--imgsz", type=int, default=640,
        help="Export image size",
    )
    parser.add_argument(
        "--half", action="store_true",
        help="FP16 half precision export",
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
        logger.error("No trained model found.")
        sys.exit(1)

    logger.info(f"Model: {model_path}")

    # Copy best.pt to models/ directory
    models_dir = CV_DIR / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    best_copy = models_dir / "best.pt"
    shutil.copy2(str(model_path), str(best_copy))
    logger.info(f"Copied best.pt to {best_copy}")

    # Export
    logger.info(f"Exporting to {args.format} format...")
    model = YOLO(str(model_path))

    export_path = model.export(
        format=args.format,
        imgsz=args.imgsz,
        half=args.half,
    )

    logger.info(f"Exported model: {export_path}")

    # Copy exported model to models/
    export_file = Path(str(export_path))
    if export_file.exists():
        dest = models_dir / export_file.name
        if export_file.is_dir():
            if dest.exists():
                shutil.rmtree(str(dest))
            shutil.copytree(str(export_file), str(dest))
        else:
            shutil.copy2(str(export_file), str(dest))
        logger.info(f"Copied export to {dest}")

    logger.info("\nExport complete:")
    logger.info(f"  PyTorch: {best_copy}")
    logger.info(f"  {args.format.upper()}: {models_dir / export_file.name}")
    logger.info("\nOriginal PyTorch model is preserved unchanged.")


if __name__ == "__main__":
    main()
