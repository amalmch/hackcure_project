"""
Annotation Visualization Script
================================
Visualizes bounding boxes and class names on sample images
from each dataset for manual inspection.

Usage:
    python scripts/visualize_annotations.py
    python scripts/visualize_annotations.py --num-samples 10
"""

import argparse
import logging
import random
import sys
from pathlib import Path

import cv2
import numpy as np
import yaml

CV_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CV_DIR))

from src.datasets.audit import parse_yolo_label


def visualize_sample(
    image_path: Path,
    label_path: Path,
    class_names: dict[int, str],
    output_path: Path,
) -> None:
    """Draw annotations on an image and save it."""
    img = cv2.imread(str(image_path))
    if img is None:
        return

    h, w = img.shape[:2]
    annotations = parse_yolo_label(label_path)

    colors = [
        (0, 255, 0), (0, 0, 255), (255, 0, 0),
        (0, 255, 255), (255, 255, 0), (255, 0, 255),
        (128, 255, 0), (0, 128, 255), (255, 128, 0),
    ]

    for ann in annotations:
        if not ann.get("valid", False):
            continue

        cid = ann["class_id"]
        bbox = ann["bbox"]  # [x_c, y_c, w, h] normalized
        x_c, y_c, bw, bh = bbox

        x1 = int((x_c - bw / 2) * w)
        y1 = int((y_c - bh / 2) * h)
        x2 = int((x_c + bw / 2) * w)
        y2 = int((y_c + bh / 2) * h)

        color = colors[cid % len(colors)]
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)

        label = class_names.get(cid, f"class_{cid}")
        cv2.putText(
            img, label, (x1, y1 - 5),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), img)


def main() -> None:
    parser = argparse.ArgumentParser(description="Visualize dataset annotations")
    parser.add_argument(
        "--num-samples", type=int, default=5,
        help="Number of samples per dataset per split",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    config_path = CV_DIR / "configs" / "datasets.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    project_root = CV_DIR.parent
    output_base = CV_DIR / "data" / "audit" / "visualizations"

    image_exts = {".jpg", ".jpeg", ".png", ".bmp"}

    for ds_key in ["tcc_person_fall", "human_fall_v2"]:
        ds_cfg = config["datasets"][ds_key]
        ds_path = project_root / ds_cfg["path"]
        class_names = {int(k): v for k, v in ds_cfg["original_classes"].items()}

        logger.info(f"Visualizing {ds_cfg['name']}")

        for split_name, split_dir in ds_cfg["splits"].items():
            images_dir = ds_path / split_dir / "images"
            labels_dir = ds_path / split_dir / "labels"

            if not images_dir.exists():
                continue

            image_files = [
                f for f in images_dir.iterdir()
                if f.suffix.lower() in image_exts
            ]
            samples = random.sample(
                image_files, min(args.num_samples, len(image_files))
            )

            for img_file in samples:
                label_file = labels_dir / (img_file.stem + ".txt")
                if not label_file.exists():
                    continue

                out_path = (
                    output_base / ds_key / split_name / img_file.name
                )
                visualize_sample(img_file, label_file, class_names, out_path)

        logger.info(f"  Saved to {output_base / ds_key}")

    logger.info(f"All visualizations saved to {output_base}")


if __name__ == "__main__":
    main()
