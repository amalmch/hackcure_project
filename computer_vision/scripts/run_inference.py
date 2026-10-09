"""
Inference Script
================
Run the full patient monitoring pipeline on images, videos, or webcam.

Usage:
    python scripts/run_inference.py --source path/to/video.mp4
    python scripts/run_inference.py --source path/to/image.jpg
    python scripts/run_inference.py --source path/to/folder/
    python scripts/run_inference.py --source 0  # webcam
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import cv2
import yaml

CV_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CV_DIR))

from src.inference import PatientMonitor


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Patient monitoring inference"
    )
    parser.add_argument(
        "--source", type=str, required=True,
        help="Image, video, folder path, or webcam index (0)",
    )
    parser.add_argument(
        "--model", type=str, default=None,
        help="Path to model weights (default: auto-find best.pt)",
    )
    parser.add_argument(
        "--conf", type=float, default=0.25,
        help="Confidence threshold",
    )
    parser.add_argument(
        "--imgsz", type=int, default=640,
        help="Inference image size",
    )
    parser.add_argument(
        "--device", type=str, default="0",
        help="CUDA device or 'cpu'",
    )
    parser.add_argument(
        "--save-video", action="store_true",
        help="Save annotated video",
    )
    parser.add_argument(
        "--save-json", action="store_true",
        help="Save structured outputs as JSON",
    )
    parser.add_argument(
        "--no-display", action="store_true",
        help="Disable display window",
    )
    parser.add_argument(
        "--max-frames", type=int, default=None,
        help="Maximum frames to process",
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
        # Auto-find best.pt
        runs_dir = CV_DIR / "runs" / "patient_yolov8n"
        model_path = None
        if runs_dir.exists():
            for exp_dir in sorted(
                runs_dir.iterdir(),
                key=lambda x: x.stat().st_mtime,
                reverse=True,
            ):
                if exp_dir.is_dir():
                    best = exp_dir / "weights" / "best.pt"
                    if best.exists():
                        model_path = best
                        break
        if model_path is None:
            # Fall back to models/ directory
            models_best = CV_DIR / "models" / "best.pt"
            if models_best.exists():
                model_path = models_best
            else:
                model_path = Path("yolov8n.pt")
                logger.warning(
                    "No trained model found. Using pretrained yolov8n.pt"
                )

    logger.info(f"Model: {model_path}")

    # Temporal config
    temporal_config = CV_DIR / "configs" / "temporal.yaml"

    # Create monitor
    monitor = PatientMonitor(
        model_path=model_path,
        confidence=args.conf,
        device=args.device,
        imgsz=args.imgsz,
        temporal_config=temporal_config,
    )

    source = args.source
    source_path = Path(source) if not source.isdigit() else None

    # JSON output collector
    all_outputs = []

    if source_path and source_path.is_file():
        ext = source_path.suffix.lower()
        if ext in {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}:
            # Single image
            logger.info(f"Processing image: {source_path}")
            annotated, outputs = monitor.process_image(source_path)

            if annotated.size > 0:
                out_path = CV_DIR / "runs" / "visualizations" / f"result_{source_path.name}"
                out_path.parent.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(out_path), annotated)
                logger.info(f"Saved to {out_path}")

            for o in outputs:
                _print_patient(o, logger)
                all_outputs.append(o)

        elif ext in {".mp4", ".avi", ".mov", ".mkv", ".wmv"}:
            # Video
            logger.info(f"Processing video: {source_path}")
            output_video = (
                CV_DIR / "runs" / "visualizations" / f"result_{source_path.name}"
                if args.save_video else None
            )

            for annotated, outputs in monitor.process_video(
                source_path,
                save_video=args.save_video,
                output_video_path=output_video,
                display=not args.no_display,
                max_frames=args.max_frames,
            ):
                all_outputs.extend(outputs)

    elif source_path and source_path.is_dir():
        # Folder of images
        logger.info(f"Processing folder: {source_path}")
        image_exts = {".jpg", ".jpeg", ".png", ".bmp"}
        images = sorted(
            f for f in source_path.iterdir()
            if f.suffix.lower() in image_exts
        )
        for img_path in images:
            annotated, outputs = monitor.process_image(img_path)
            for o in outputs:
                _print_patient(o, logger)
                all_outputs.append(o)

    elif source.isdigit():
        # Webcam
        logger.info(f"Processing webcam: {source}")
        for annotated, outputs in monitor.process_video(
            int(source),
            display=not args.no_display,
            max_frames=args.max_frames,
        ):
            all_outputs.extend(outputs)

    else:
        logger.error(f"Invalid source: {source}")
        sys.exit(1)

    # Save JSON outputs
    if args.save_json and all_outputs:
        json_path = CV_DIR / "runs" / "visualizations" / "inference_output.json"
        json_path.parent.mkdir(parents=True, exist_ok=True)

        # Remove non-serializable trajectory data
        clean_outputs = []
        for o in all_outputs:
            clean = {k: v for k, v in o.items() if k != "trajectory"}
            clean_outputs.append(clean)

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(clean_outputs, f, indent=2, default=str)
        logger.info(f"JSON outputs saved to {json_path}")


def _print_patient(output: dict, logger: logging.Logger) -> None:
    """Print a single patient output."""
    pid = output.get("patient_id", "?")
    state = output.get("state", "unknown")
    conf = output.get("confidence", 0)
    movement = output.get("movement", {}).get("state", "")
    fall = output.get("fall_event", {})
    disc = output.get("possible_discomfort", {})

    status = f"Patient #{pid:02d} | {state} ({conf:.2f}) | Movement: {movement}"
    if fall.get("detected"):
        status += f" | FALL CONFIRMED ({fall['confidence']:.2f})"
    if disc.get("detected"):
        status += f" | Discomfort ({disc['confidence']:.2f})"
    logger.info(status)


if __name__ == "__main__":
    main()
