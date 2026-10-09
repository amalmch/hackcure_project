"""
YOLO Dataset Validation Script
================================
Validates every processed annotation in the unified dataset.
Must pass before training can proceed.

Usage:
    python scripts/validate_yolo_dataset.py
"""

import logging
import sys
from pathlib import Path

import yaml

CV_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CV_DIR))


def validate_yolo_dataset(data_yaml_path: Path) -> dict:
    """
    Validate every label in the processed YOLO dataset.

    Returns:
        Validation results dict.
    """
    logger = logging.getLogger(__name__)

    with open(data_yaml_path, "r", encoding="utf-8") as f:
        data_cfg = yaml.safe_load(f)

    dataset_root = Path(data_cfg["path"])
    class_names = data_cfg.get("names", {})
    num_classes = len(class_names)
    valid_class_ids = set(int(k) for k in class_names.keys())

    results = {
        "valid": True,
        "total_images": 0,
        "total_labels": 0,
        "total_annotations": 0,
        "errors": [],
        "warnings": [],
        "per_split": {},
    }

    image_exts = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}

    for split in ["train", "val", "test"]:
        images_dir = dataset_root / "images" / split
        labels_dir = dataset_root / "labels" / split

        split_results = {
            "images": 0,
            "labels": 0,
            "annotations": 0,
            "missing_labels": 0,
            "missing_images": 0,
            "empty_labels": 0,
            "errors": [],
        }

        if not images_dir.exists():
            msg = f"Images directory not found: {images_dir}"
            results["errors"].append(msg)
            results["valid"] = False
            results["per_split"][split] = split_results
            continue

        image_files = sorted(
            f for f in images_dir.iterdir()
            if f.suffix.lower() in image_exts
        )
        split_results["images"] = len(image_files)
        results["total_images"] += len(image_files)

        for img_file in image_files:
            label_file = labels_dir / (img_file.stem + ".txt")

            if not label_file.exists():
                split_results["missing_labels"] += 1
                continue

            split_results["labels"] += 1
            results["total_labels"] += 1

            # Read and validate each line
            try:
                content = label_file.read_text(encoding="utf-8").strip()
            except Exception as e:
                split_results["errors"].append(
                    f"Cannot read {label_file.name}: {e}"
                )
                results["valid"] = False
                continue

            if not content:
                split_results["empty_labels"] += 1
                continue

            for line_num, line in enumerate(content.split("\n"), 1):
                line = line.strip()
                if not line:
                    continue

                parts = line.split()

                # Must have at least 5 values
                if len(parts) < 5:
                    error = (
                        f"{label_file.name}:{line_num}: "
                        f"Too few values ({len(parts)}), need 5"
                    )
                    split_results["errors"].append(error)
                    results["valid"] = False
                    continue

                if len(parts) != 5:
                    error = (
                        f"{label_file.name}:{line_num}: "
                        f"Expected 5 values for detection, got {len(parts)}"
                    )
                    split_results["errors"].append(error)
                    results["valid"] = False
                    continue

                # Validate class ID
                try:
                    class_id = int(parts[0])
                except ValueError:
                    error = (
                        f"{label_file.name}:{line_num}: "
                        f"Non-integer class ID: {parts[0]}"
                    )
                    split_results["errors"].append(error)
                    results["valid"] = False
                    continue

                if class_id not in valid_class_ids:
                    error = (
                        f"{label_file.name}:{line_num}: "
                        f"Unknown class ID {class_id}, "
                        f"valid: {valid_class_ids}"
                    )
                    split_results["errors"].append(error)
                    results["valid"] = False
                    continue

                # Validate coordinates
                try:
                    x_c, y_c, w, h = [float(v) for v in parts[1:5]]
                except ValueError:
                    error = (
                        f"{label_file.name}:{line_num}: "
                        f"Non-numeric coordinates"
                    )
                    split_results["errors"].append(error)
                    results["valid"] = False
                    continue

                # Range checks
                for name, val in [("x_center", x_c), ("y_center", y_c)]:
                    if val < 0 or val > 1:
                        error = (
                            f"{label_file.name}:{line_num}: "
                            f"{name}={val} out of range [0, 1]"
                        )
                        split_results["errors"].append(error)
                        results["valid"] = False

                for name, val in [("width", w), ("height", h)]:
                    if val <= 0:
                        error = (
                            f"{label_file.name}:{line_num}: "
                            f"{name}={val} must be > 0"
                        )
                        split_results["errors"].append(error)
                        results["valid"] = False
                    if val > 1:
                        results["warnings"].append(
                            f"{label_file.name}:{line_num}: "
                            f"{name}={val} > 1.0"
                        )

                split_results["annotations"] += 1
                results["total_annotations"] += 1

        # Check for labels without images
        if labels_dir.exists():
            for lbl_file in labels_dir.glob("*.txt"):
                has_image = any(
                    (images_dir / (lbl_file.stem + ext)).exists()
                    for ext in image_exts
                )
                if not has_image:
                    split_results["missing_images"] += 1

        results["per_split"][split] = split_results

    return results


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger(__name__)

    data_yaml = CV_DIR / "data" / "processed" / "patient_detection" / "data.yaml"

    if not data_yaml.exists():
        logger.error(
            f"data.yaml not found at {data_yaml}. "
            "Run scripts/build_dataset.py first."
        )
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("YOLO DATASET VALIDATION")
    logger.info("=" * 60)

    results = validate_yolo_dataset(data_yaml)

    # Print results
    logger.info(f"Total images: {results['total_images']}")
    logger.info(f"Total labels: {results['total_labels']}")
    logger.info(f"Total annotations: {results['total_annotations']}")

    for split, info in results["per_split"].items():
        logger.info(f"\n  {split}:")
        logger.info(f"    Images: {info['images']}")
        logger.info(f"    Labels: {info['labels']}")
        logger.info(f"    Annotations: {info['annotations']}")
        logger.info(f"    Missing labels: {info['missing_labels']}")
        logger.info(f"    Empty labels: {info['empty_labels']}")
        if info["errors"]:
            logger.error(f"    Errors: {len(info['errors'])}")
            for err in info["errors"][:10]:
                logger.error(f"      {err}")

    if results["warnings"]:
        logger.warning(f"\nWarnings: {len(results['warnings'])}")
        for w in results["warnings"][:10]:
            logger.warning(f"  {w}")

    if results["valid"]:
        logger.info("\n✓ VALIDATION PASSED - Dataset is ready for training")
    else:
        logger.error(
            f"\n✗ VALIDATION FAILED - {len(results['errors'])} errors found"
        )
        logger.error("Fix all errors before training.")
        sys.exit(1)


if __name__ == "__main__":
    main()
