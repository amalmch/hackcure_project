"""
YOLOv8n Training Script
========================
Trains the patient detection model using the processed dataset.
Reads all configuration from configs/training.yaml.
Includes batch-size fallback for VRAM limitations.

Usage:
    python scripts/train_patient_yolo.py
    python scripts/train_patient_yolo.py --experiment my_experiment
    python scripts/train_patient_yolo.py --batch -1  # AutoBatch
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import torch
import yaml
from ultralytics import YOLO

CV_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CV_DIR))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train YOLOv8n patient detection model"
    )
    parser.add_argument(
        "--experiment", type=str, default=None,
        help="Experiment name (default: auto-generated)",
    )
    parser.add_argument(
        "--batch", type=int, default=None,
        help="Override batch size (-1 for AutoBatch)",
    )
    parser.add_argument(
        "--epochs", type=int, default=None,
        help="Override number of epochs",
    )
    parser.add_argument(
        "--resume", type=str, default=None,
        help="Resume from checkpoint path",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger(__name__)

    # Load configs
    training_cfg_path = CV_DIR / "configs" / "training.yaml"
    with open(training_cfg_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    data_yaml = CV_DIR / "data" / "processed" / "patient_detection" / "data.yaml"
    if not data_yaml.exists():
        logger.error(f"data.yaml not found: {data_yaml}")
        sys.exit(1)

    # Validate dataset first
    logger.info("Validating dataset before training...")
    from scripts.validate_yolo_dataset import validate_yolo_dataset  # type: ignore
    validation = validate_yolo_dataset(data_yaml)
    if not validation["valid"]:
        logger.error("Dataset validation FAILED. Fix errors before training.")
        sys.exit(1)
    logger.info("✓ Dataset validation passed")

    # Print dataset stats
    with open(data_yaml, "r", encoding="utf-8") as f:
        data_cfg = yaml.safe_load(f)
    logger.info(f"Classes ({data_cfg.get('nc', '?')}): {data_cfg['names']}")
    dataset_root = Path(data_cfg["path"])
    for split in ["train", "val", "test"]:
        img_dir = dataset_root / "images" / split
        if img_dir.exists():
            count = len(list(img_dir.glob("*")))
            logger.info(f"  {split}: {count} images")

    # Training parameters
    t = config["training"]
    aug = config.get("augmentation", {})

    epochs = args.epochs or t["epochs"]
    imgsz = t["imgsz"]
    device = t["device"]
    seed = t["seed"]

    # Check GPU
    if torch.cuda.is_available():
        gpu_name = torch.cuda.get_device_name(0)
        gpu_mem = torch.cuda.get_device_properties(0).total_memory / 1e9
        logger.info(f"GPU: {gpu_name} ({gpu_mem:.1f} GB VRAM)")
    else:
        logger.warning("No CUDA GPU. Training on CPU (slow).")
        device = "cpu"

    # Experiment naming
    exp_name = args.experiment or config["output"].get("name", "baseline")
    project_dir = str(CV_DIR / config["output"]["project"])

    # Batch size with fallback
    batch_sizes = [args.batch] if args.batch is not None else t.get("batch_fallback", [16, 8, 4])

    model_weights = args.resume or config["model"]["weights"]
    logger.info(f"Loading model: {model_weights}")
    model = YOLO(model_weights)

    # Training args (excluding batch which we'll try in order)
    train_kwargs = {
        "data": str(data_yaml),
        "epochs": epochs,
        "imgsz": imgsz,
        "device": device,
        "patience": t["patience"],
        "seed": seed,
        "amp": t["amp"],
        "workers": t["workers"],
        "close_mosaic": t["close_mosaic"],
        "optimizer": t["optimizer"],
        "lr0": t["lr0"],
        "lrf": t["lrf"],
        "weight_decay": t["weight_decay"],
        "warmup_epochs": t["warmup_epochs"],
        "project": project_dir,
        "name": exp_name,
        "exist_ok": t.get("exist_ok", False),
        "verbose": True,
        # Augmentation
        "hsv_h": aug.get("hsv_h", 0.015),
        "hsv_s": aug.get("hsv_s", 0.5),
        "hsv_v": aug.get("hsv_v", 0.3),
        "degrees": aug.get("degrees", 5.0),
        "translate": aug.get("translate", 0.1),
        "scale": aug.get("scale", 0.5),
        "shear": aug.get("shear", 2.0),
        "perspective": aug.get("perspective", 0.0005),
        "fliplr": aug.get("fliplr", 0.5),
        "flipud": aug.get("flipud", 0.0),
        "mosaic": aug.get("mosaic", 0.7),
        "mixup": aug.get("mixup", 0.05),
    }

    if args.resume:
        train_kwargs["resume"] = True

    # Try batch sizes in order
    results = None
    used_batch = None
    for batch in batch_sizes:
        logger.info(f"\nAttempting training with batch={batch}")
        try:
            train_kwargs["batch"] = batch
            start_time = time.time()
            results = model.train(**train_kwargs)
            elapsed = time.time() - start_time
            used_batch = batch
            logger.info(f"Training completed in {elapsed/60:.1f} minutes")
            break
        except RuntimeError as e:
            if "out of memory" in str(e).lower() and batch != batch_sizes[-1]:
                logger.warning(
                    f"CUDA OOM with batch={batch}. "
                    f"Retrying with smaller batch..."
                )
                torch.cuda.empty_cache()
                # Reload model for fresh start
                model = YOLO(model_weights)
                continue
            else:
                logger.error(f"Training failed: {e}")
                sys.exit(1)

    if results is None:
        logger.error("Training failed with all batch sizes.")
        sys.exit(1)

    # Save experiment metadata
    exp_dir = Path(project_dir) / exp_name
    metadata = {
        "timestamp": datetime.now().isoformat(),
        "model": config["model"]["weights"],
        "batch_size": used_batch,
        "epochs": epochs,
        "imgsz": imgsz,
        "seed": seed,
        "device": str(device),
        "data_yaml": str(data_yaml),
        "training_config": str(training_cfg_path),
        "classes": data_cfg["names"],
    }

    meta_path = exp_dir / "experiment_metadata.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    logger.info(f"\n{'='*60}")
    logger.info("TRAINING COMPLETE")
    logger.info(f"{'='*60}")
    logger.info(f"Experiment: {exp_dir}")
    logger.info(f"Best weights: {exp_dir / 'weights' / 'best.pt'}")
    logger.info(f"Last weights: {exp_dir / 'weights' / 'last.pt'}")


if __name__ == "__main__":
    main()
