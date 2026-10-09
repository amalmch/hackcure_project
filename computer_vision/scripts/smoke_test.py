"""
Smoke Test Script
=================
Trains YOLOv8n for 1 epoch to verify the entire pipeline works:
dataset, model, GPU, forward/backward pass, validation.

Usage:
    python scripts/smoke_test.py
"""

import logging
import sys
import torch
from pathlib import Path

import yaml
from ultralytics import YOLO

CV_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CV_DIR))


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("SMOKE TEST - 1 Epoch Training Verification")
    logger.info("=" * 60)

    # Check data.yaml
    data_yaml = CV_DIR / "data" / "processed" / "patient_detection" / "data.yaml"
    if not data_yaml.exists():
        logger.error(f"data.yaml not found: {data_yaml}")
        logger.error("Run scripts/build_dataset.py first.")
        sys.exit(1)

    with open(data_yaml, "r", encoding="utf-8") as f:
        data_cfg = yaml.safe_load(f)

    logger.info(f"Dataset: {data_cfg['path']}")
    logger.info(f"Classes: {data_cfg['names']}")
    logger.info(f"NC: {data_cfg.get('nc', len(data_cfg['names']))}")

    # Check training config
    training_cfg_path = CV_DIR / "configs" / "training.yaml"
    with open(training_cfg_path, "r", encoding="utf-8") as f:
        training_cfg = yaml.safe_load(f)

    smoke_cfg = training_cfg.get("smoke_test", {})
    epochs = smoke_cfg.get("epochs", 1)
    batch = smoke_cfg.get("batch", 4)
    imgsz = smoke_cfg.get("imgsz", 640)
    device_cfg = smoke_cfg.get("device", 0)

    # Check GPU
    if torch.cuda.is_available():
        gpu_name = torch.cuda.get_device_name(0)
        gpu_mem = torch.cuda.get_device_properties(0).total_mem / 1e9
        logger.info(f"GPU: {gpu_name} ({gpu_mem:.1f} GB)")
        device = device_cfg
    else:
        logger.warning("No CUDA GPU found, using CPU")
        device = "cpu"

    # Count images
    dataset_root = Path(data_cfg["path"])
    for split in ["train", "val", "test"]:
        img_dir = dataset_root / "images" / split
        if img_dir.exists():
            count = len(list(img_dir.glob("*")))
            logger.info(f"  {split} images: {count}")

    # Load model
    logger.info("Loading YOLOv8n pretrained weights...")
    model = YOLO("yolov8n.pt")
    logger.info("Model loaded successfully")

    # Train 1 epoch
    logger.info(f"Starting smoke test: {epochs} epoch, batch={batch}, imgsz={imgsz}")
    try:
        results = model.train(
            data=str(data_yaml),
            epochs=epochs,
            imgsz=imgsz,
            batch=batch,
            device=device,
            patience=1,
            seed=42,
            amp=True,
            workers=4,
            project=str(CV_DIR / "runs" / "smoke_test"),
            name="smoke",
            exist_ok=True,
            verbose=True,
        )
        logger.info("✓ Training completed successfully")
    except RuntimeError as e:
        if "out of memory" in str(e).lower():
            logger.error(f"CUDA OOM with batch={batch}. Try reducing batch size.")
        else:
            logger.error(f"Training failed: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Training failed: {e}")
        sys.exit(1)

    # Validate
    logger.info("Running validation...")
    try:
        val_results = model.val(
            data=str(data_yaml),
            device=device,
            imgsz=imgsz,
            verbose=True,
        )
        logger.info(f"Validation mAP50: {val_results.box.map50:.4f}")
        logger.info("✓ Validation completed successfully")
    except Exception as e:
        logger.error(f"Validation failed: {e}")
        sys.exit(1)

    logger.info("")
    logger.info("=" * 60)
    logger.info("✓ SMOKE TEST PASSED")
    logger.info("  - Dataset loads correctly")
    logger.info("  - Model initializes correctly")
    logger.info("  - Forward/backward pass works")
    logger.info("  - Validation works")
    logger.info("  Ready for full training.")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
