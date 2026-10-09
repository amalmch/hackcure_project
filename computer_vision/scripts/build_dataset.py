"""
Build Dataset Script
====================
Merges compatible annotations into a unified YOLO detection dataset.

Usage:
    python scripts/build_dataset.py
"""

import logging
import sys
from pathlib import Path

CV_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CV_DIR))

from src.datasets.build_dataset import build_dataset


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("BUILD UNIFIED YOLO DATASET")
    logger.info("=" * 60)

    stats = build_dataset(CV_DIR)

    logger.info("\nBuild complete.")
    logger.info(f"Dataset: {CV_DIR / 'data' / 'processed' / 'patient_detection'}")
    logger.info(f"data.yaml: {CV_DIR / 'data' / 'processed' / 'patient_detection' / 'data.yaml'}")
    logger.info(f"Manifest: {CV_DIR / 'data' / 'manifests' / 'patient_detection_manifest.csv'}")


if __name__ == "__main__":
    main()
