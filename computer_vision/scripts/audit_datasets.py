"""
Dataset Audit Script
====================
Inspects all three local datasets and produces audit reports.

Usage:
    python scripts/audit_datasets.py
"""

import logging
import sys
from pathlib import Path

# Add project root to path
CV_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CV_DIR))

from src.datasets.audit import run_full_audit


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("DATASET AUDIT")
    logger.info("=" * 60)

    audits = run_full_audit(CV_DIR)

    for audit in audits:
        logger.info(f"\n{'='*40}")
        logger.info(f"Dataset: {audit['name']}")
        logger.info(f"Path: {audit['path']}")
        logger.info(f"Format: {audit['annotation_format']}")

        if audit["annotation_format"] == "video_csv":
            totals = audit["totals"]
            logger.info(f"Subjects: {totals['total_subjects']}")
            logger.info(f"Videos: {totals['videos']}")
            logger.info(f"Temporal classes: {audit.get('temporal_classes', [])}")
        else:
            totals = audit["totals"]
            logger.info(f"Images: {totals['images']}")
            logger.info(f"Labels: {totals['labels']}")
            logger.info(f"Bboxes: {totals['bboxes']}")
            logger.info(f"Missing labels: {totals['missing_labels']}")
            logger.info(f"Empty labels: {totals['empty_labels']}")
            logger.info(f"Malformed: {totals['malformed_labels']}")
            logger.info(f"Duplicates: {audit.get('duplicate_images', 0)}")
            logger.info(f"Class distribution: {audit.get('class_distribution', {})}")

    logger.info("\nAudit reports saved to:")
    logger.info(f"  reports/dataset_audit.md")
    logger.info(f"  data/manifests/dataset_audit.json")


if __name__ == "__main__":
    main()
