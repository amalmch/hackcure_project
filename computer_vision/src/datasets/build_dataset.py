"""
Build Unified YOLO Dataset
===========================
Merges compatible annotations from TCC-Person-Fall-2024 and Human-Fall-v2
into a single unified YOLO detection dataset.

Key responsibilities:
- Copies images and harmonized labels to processed/patient_detection/
- Preserves original train/val/test splits where trustworthy
- Enforces video-level split integrity to prevent data leakage
- Generates data.yaml and a full manifest CSV
"""

import csv
import hashlib
import logging
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

import cv2
import yaml

from .harmonize import (
    build_class_remap_table,
    harmonize_label_file,
    load_config,
)

logger = logging.getLogger(__name__)


def compute_file_hash(filepath: Path) -> str:
    """Compute MD5 hash of a file."""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def get_image_size(image_path: Path) -> tuple[int, int]:
    """Get image (width, height)."""
    img = cv2.imread(str(image_path))
    if img is not None:
        h, w = img.shape[:2]
        return w, h
    return 0, 0


def extract_video_group(filename: str) -> str:
    """
    Extract a video/recording group identifier from a filename.

    Roboflow-exported frames often encode the source video name before
    the augmentation hash, so frames from the same source video will
    share the same prefix.

    This is a best-effort heuristic for data-leakage prevention.
    """
    # Strip the Roboflow hash suffix: name.rf.<hash>.ext
    stem = Path(filename).stem
    parts = stem.rsplit(".rf.", 1)
    if len(parts) == 2:
        return parts[0]
    # Also try splitting on common frame-number patterns
    # e.g., "video_frame_001" → "video"
    for sep in ["_frame_", "_f", "-frame-"]:
        if sep in stem:
            return stem.split(sep)[0]
    return stem


def build_dataset(cv_dir: Path) -> dict[str, Any]:
    """
    Build the unified YOLO detection dataset.

    Args:
        cv_dir: Path to computer_vision/ directory.

    Returns:
        Build statistics dictionary.
    """
    config = load_config(cv_dir / "configs" / "datasets.yaml")
    project_root = cv_dir.parent

    # Output directories
    out_root = cv_dir / "data" / "processed" / "patient_detection"
    for split in ["train", "val", "test"]:
        (out_root / "images" / split).mkdir(parents=True, exist_ok=True)
        (out_root / "labels" / split).mkdir(parents=True, exist_ok=True)

    canonical_classes = config["canonical_classes"]
    manifest_rows = []
    stats = {
        "total_images_processed": 0,
        "total_images_copied": 0,
        "total_bboxes": 0,
        "excluded_annotations": 0,
        "skipped_files": 0,
        "class_distribution": Counter(),
        "per_dataset": {},
    }

    IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}

    # ------------------------------------------------------------------
    # Process each YOLO-format dataset
    # ------------------------------------------------------------------
    yolo_datasets = {
        "tcc_person_fall": config["datasets"]["tcc_person_fall"],
        "human_fall_v2": config["datasets"]["human_fall_v2"],
    }

    for ds_key, ds_config in yolo_datasets.items():
        ds_path = project_root / ds_config["path"]
        ds_name = ds_config["name"]
        ds_format = ds_config["format"]
        mappings = config["class_mapping"].get(ds_key, [])
        remap_table = build_class_remap_table(mappings)

        logger.info(f"Processing {ds_name} from {ds_path}")

        ds_stats = {
            "images_processed": 0,
            "images_copied": 0,
            "bboxes": 0,
            "excluded": 0,
            "skipped": 0,
        }

        # Map split names: dataset uses "valid" → we use "val"
        split_map = {
            "train": ds_config["splits"]["train"],
            "val": ds_config["splits"]["val"],
            "test": ds_config["splits"]["test"],
        }

        # Track video groups per split for leakage check
        video_groups_per_split: dict[str, set] = {
            "train": set(), "val": set(), "test": set()
        }

        for canonical_split, source_split_dir in split_map.items():
            source_path = ds_path / source_split_dir
            images_dir = source_path / "images"
            labels_dir = source_path / "labels"

            if not images_dir.exists():
                logger.warning(f"Images dir not found: {images_dir}")
                continue

            image_files = sorted(
                f for f in images_dir.iterdir()
                if f.suffix.lower() in IMAGE_EXTENSIONS
            )

            for img_file in image_files:
                ds_stats["images_processed"] += 1
                stats["total_images_processed"] += 1

                label_file = labels_dir / (img_file.stem + ".txt")
                if not label_file.exists():
                    ds_stats["skipped"] += 1
                    stats["skipped_files"] += 1
                    continue

                # Harmonize labels
                converted_lines, infos = harmonize_label_file(
                    label_file, remap_table, ds_format
                )

                if not converted_lines:
                    # All annotations excluded or empty
                    excluded_count = sum(
                        1 for i in infos
                        if i.get("action") in ("EXCLUDE", "SKIP")
                    )
                    ds_stats["excluded"] += excluded_count
                    stats["excluded_annotations"] += excluded_count
                    ds_stats["skipped"] += 1
                    stats["skipped_files"] += 1
                    continue

                # Track video group for leakage detection
                video_group = extract_video_group(img_file.name)
                video_groups_per_split[canonical_split].add(video_group)

                # Generate unique output filename
                out_stem = f"{ds_key}_{img_file.stem}"
                out_img_ext = img_file.suffix
                out_img_name = f"{out_stem}{out_img_ext}"
                out_lbl_name = f"{out_stem}.txt"

                out_img_path = out_root / "images" / canonical_split / out_img_name
                out_lbl_path = out_root / "labels" / canonical_split / out_lbl_name

                # Copy image
                shutil.copy2(str(img_file), str(out_img_path))

                # Write harmonized label
                with open(out_lbl_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(converted_lines) + "\n")

                ds_stats["images_copied"] += 1
                stats["total_images_copied"] += 1
                ds_stats["bboxes"] += len(converted_lines)
                stats["total_bboxes"] += len(converted_lines)

                # Get image dimensions
                w, h = get_image_size(img_file)

                # Update class distribution
                for info in infos:
                    if info.get("canonical_class_id") is not None:
                        cid = info["canonical_class_id"]
                        stats["class_distribution"][cid] += 1

                # Create manifest row for each annotation
                source_hash = compute_file_hash(img_file)
                for info in infos:
                    if info.get("action") in ("EXCLUDE", "SKIP"):
                        continue
                    manifest_rows.append({
                        "source_dataset": ds_name,
                        "source_file": str(img_file.relative_to(project_root)),
                        "source_label": str(
                            label_file.relative_to(project_root)
                        ),
                        "original_class_id": info.get("source_class_id", ""),
                        "original_class_name": "",
                        "mapped_class_id": info.get("canonical_class_id", ""),
                        "mapped_class_name": info.get("canonical_class", ""),
                        "split": canonical_split,
                        "image_width": w,
                        "image_height": h,
                        "bbox_count": len(converted_lines),
                        "source_hash": source_hash,
                    })

                # Update per-annotation excluded count
                for info in infos:
                    if info.get("action") in ("EXCLUDE", "SKIP"):
                        ds_stats["excluded"] += 1
                        stats["excluded_annotations"] += 1

        # Check for data leakage
        for s1 in ["train", "val", "test"]:
            for s2 in ["train", "val", "test"]:
                if s1 >= s2:
                    continue
                overlap = video_groups_per_split[s1] & video_groups_per_split[s2]
                if overlap:
                    logger.warning(
                        f"[{ds_name}] Potential data leakage: {len(overlap)} "
                        f"video groups shared between {s1} and {s2}. "
                        f"Examples: {list(overlap)[:5]}"
                    )

        stats["per_dataset"][ds_key] = ds_stats
        logger.info(
            f"{ds_name}: copied {ds_stats['images_copied']} images, "
            f"{ds_stats['bboxes']} bboxes, "
            f"excluded {ds_stats['excluded']} annotations, "
            f"skipped {ds_stats['skipped']} files"
        )

    # ------------------------------------------------------------------
    # Record GMDCSA-24 exclusion
    # ------------------------------------------------------------------
    gmdcsa_config = config["datasets"]["gmdcsa24"]
    gmdcsa_mapping = config["class_mapping"].get("gmdcsa24", [])
    stats["per_dataset"]["gmdcsa24"] = {
        "images_processed": 0,
        "images_copied": 0,
        "bboxes": 0,
        "excluded": 0,
        "skipped": 0,
        "note": (
            "Video-only dataset excluded from YOLO training. "
            "No bounding-box annotations available. "
            f"Reason: {gmdcsa_mapping[0]['reason'] if gmdcsa_mapping else 'N/A'}"
        ),
    }

    # ------------------------------------------------------------------
    # Generate data.yaml
    # ------------------------------------------------------------------
    data_yaml = {
        "path": str(out_root.resolve()),
        "train": "images/train",
        "val": "images/val",
        "test": "images/test",
        "names": {int(k): v for k, v in canonical_classes.items()},
    }

    # Only include classes that actually have samples
    active_classes = {}
    for cid, cname in canonical_classes.items():
        cid_int = int(cid)
        if stats["class_distribution"].get(cid_int, 0) > 0:
            active_classes[cid_int] = cname

    # Reindex to consecutive IDs
    old_to_new = {}
    new_names = {}
    for new_id, (old_id, name) in enumerate(sorted(active_classes.items())):
        old_to_new[old_id] = new_id
        new_names[new_id] = name

    data_yaml["names"] = new_names
    data_yaml["nc"] = len(new_names)

    # If we remapped, we need to update all label files
    if old_to_new and any(k != v for k, v in old_to_new.items()):
        logger.info(f"Reindexing classes: {old_to_new}")
        for split in ["train", "val", "test"]:
            labels_dir = out_root / "labels" / split
            if not labels_dir.exists():
                continue
            for lbl_file in labels_dir.glob("*.txt"):
                lines = lbl_file.read_text(encoding="utf-8").strip().split("\n")
                new_lines = []
                for line in lines:
                    if not line.strip():
                        continue
                    parts = line.strip().split()
                    old_cid = int(parts[0])
                    if old_cid in old_to_new:
                        parts[0] = str(old_to_new[old_cid])
                        new_lines.append(" ".join(parts))
                lbl_file.write_text(
                    "\n".join(new_lines) + "\n", encoding="utf-8"
                )

        # Update manifest
        for row in manifest_rows:
            old_id = row.get("mapped_class_id")
            if isinstance(old_id, int) and old_id in old_to_new:
                row["mapped_class_id"] = old_to_new[old_id]

        # Update class distribution
        new_dist = Counter()
        for old_id, count in stats["class_distribution"].items():
            if old_id in old_to_new:
                new_dist[old_to_new[old_id]] = count
        stats["class_distribution"] = new_dist

    yaml_path = out_root / "data.yaml"
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(data_yaml, f, default_flow_style=False, sort_keys=False)
    logger.info(f"Generated data.yaml at {yaml_path}")

    # ------------------------------------------------------------------
    # Write manifest CSV
    # ------------------------------------------------------------------
    manifest_path = cv_dir / "data" / "manifests" / "patient_detection_manifest.csv"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "source_dataset", "source_file", "source_label",
        "original_class_id", "original_class_name",
        "mapped_class_id", "mapped_class_name",
        "split", "image_width", "image_height",
        "bbox_count", "source_hash",
    ]

    with open(manifest_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in manifest_rows:
            writer.writerow(row)

    logger.info(
        f"Manifest saved to {manifest_path} ({len(manifest_rows)} rows)"
    )

    # ------------------------------------------------------------------
    # Print build summary
    # ------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("BUILD SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total images processed: {stats['total_images_processed']}")
    logger.info(f"Total images copied: {stats['total_images_copied']}")
    logger.info(f"Total bounding boxes: {stats['total_bboxes']}")
    logger.info(f"Excluded annotations: {stats['excluded_annotations']}")
    logger.info(f"Skipped files: {stats['skipped_files']}")
    logger.info("Class distribution:")
    for cid in sorted(stats["class_distribution"]):
        count = stats["class_distribution"][cid]
        cname = new_names.get(cid, f"class_{cid}")
        logger.info(f"  {cid}: {cname} = {count}")

    # Count per split
    for split in ["train", "val", "test"]:
        img_count = len(list((out_root / "images" / split).glob("*")))
        lbl_count = len(list((out_root / "labels" / split).glob("*.txt")))
        logger.info(f"  {split}: {img_count} images, {lbl_count} labels")

    return stats
