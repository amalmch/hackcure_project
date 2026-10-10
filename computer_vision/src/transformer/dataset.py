"""
Dataset and Feature Extraction Pipeline for Patient Transformer
================================================================
Extracts bounding-box crops of patients and caches DINOv2 embeddings.
"""

from __future__ import annotations
import logging
from pathlib import Path
from typing import Dict, List, Tuple

import cv2
import numpy as np
from PIL import Image
import torch
from torch.utils.data import Dataset, DataLoader
import torchvision.transforms as T
from tqdm import tqdm

logger = logging.getLogger("hackcure.transformer.dataset")

DINO_TRANSFORM = T.Compose([
    T.Resize((224, 224)),
    T.ToTensor(),
    T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
])


def extract_crops_from_labels(
    image_dir: Path,
    label_dir: Path,
    padding: float = 0.1,
) -> List[Tuple[Image.Image, int, str]]:
    """
    Extracts all patient crops and their class labels from a YOLO split.
    Returns: list of (PIL.Image crop, class_id, source_image_name)
    """
    crops = []
    label_files = sorted(list(label_dir.glob("*.txt")))

    for lbl_path in label_files:
        img_path = image_dir / f"{lbl_path.stem}.jpg"
        if not img_path.exists():
            img_path = image_dir / f"{lbl_path.stem}.png"
        if not img_path.exists():
            continue

        lines = lbl_path.read_text(encoding="utf-8").strip().splitlines()
        if not lines:
            continue

        img_bgr = cv2.imread(str(img_path))
        if img_bgr is None:
            continue
        h_img, w_img = img_bgr.shape[:2]
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)

        for line in lines:
            parts = line.strip().split()
            if len(parts) < 5:
                continue
            class_id = int(parts[0])
            cx, cy, w, h = map(float, parts[1:5])

            # Convert normalized YOLO bbox to pixel coordinates with padding
            pad_w = w * padding
            pad_h = h * padding

            x1 = max(0, int((cx - (w / 2) - pad_w) * w_img))
            y1 = max(0, int((cy - (h / 2) - pad_h) * h_img))
            x2 = min(w_img, int((cx + (w / 2) + pad_w) * w_img))
            y2 = min(h_img, int((cy + (h / 2) + pad_h) * h_img))

            if (x2 - x1) < 12 or (y2 - y1) < 12:
                continue  # skip degenerated / tiny crops

            crop_np = img_rgb[y1:y2, x1:x2]
            crop_pil = Image.fromarray(crop_np)
            crops.append((crop_pil, class_id, img_path.name))

    return crops


class PatientFeatureDataset(Dataset):
    """
    PyTorch Dataset serving pre-computed DINOv2 features for fast training.
    """
    def __init__(
        self,
        cls_tokens: torch.Tensor,
        patch_tokens: torch.Tensor,
        labels: torch.Tensor,
    ):
        self.cls_tokens = cls_tokens
        self.patch_tokens = patch_tokens
        self.labels = labels

    def __len__(self) -> int:
        return len(self.labels)

    def __getitem__(self, idx: int) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        return self.cls_tokens[idx], self.patch_tokens[idx], self.labels[idx]


def get_or_extract_features(
    data_dir: Path,
    cache_path: Path,
    device: str = "cuda" if torch.cuda.is_available() else "cpu",
    batch_size: int = 32,
    force_recompute: bool = False,
) -> Dict[str, PatientFeatureDataset]:
    """
    Extracts features for train, val, and test splits using DINOv2 and caches them.
    """
    if cache_path.exists() and not force_recompute:
        logger.info(f"Loading cached DINOv2 features from {cache_path}...")
        data = torch.load(cache_path, map_location="cpu", weights_only=True)
        return {
            split: PatientFeatureDataset(
                data[split]["cls"],
                data[split]["patches"],
                data[split]["labels"],
            )
            for split in ["train", "val", "test"]
        }

    logger.info("Extracting DINOv2 features from scratch...")
    logger.info("Loading DINOv2 ViT-S/14 backbone...")
    backbone = torch.hub.load("facebookresearch/dinov2", "dinov2_vits14").to(device)
    backbone.eval()

    splits_data = {}
    for split in ["train", "val", "test"]:
        img_dir = data_dir / "images" / split
        lbl_dir = data_dir / "labels" / split
        logger.info(f"Processing {split} split from {img_dir}...")

        crops = extract_crops_from_labels(img_dir, lbl_dir)
        logger.info(f"Extracted {len(crops)} crops for {split}.")

        cls_list = []
        patch_list = []
        label_list = []

        # Batch forward pass through backbone
        for i in range(0, len(crops), batch_size):
            batch_items = crops[i : i + batch_size]
            tensors = torch.stack([DINO_TRANSFORM(item[0]) for item in batch_items]).to(device)
            batch_labels = [item[1] for item in batch_items]

            with torch.no_grad():
                feat = backbone.forward_features(tensors)
                cls_list.append(feat["x_norm_clstoken"].cpu())
                patch_list.append(feat["x_norm_patchtokens"].cpu())
                label_list.extend(batch_labels)

        splits_data[split] = {
            "cls": torch.cat(cls_list, dim=0) if cls_list else torch.empty(0, 384),
            "patches": torch.cat(patch_list, dim=0) if patch_list else torch.empty(0, 256, 384),
            "labels": torch.tensor(label_list, dtype=torch.long),
        }
        logger.info(
            f"✓ {split}: {len(splits_data[split]['labels'])} samples "
            f"(falling={int((splits_data[split]['labels'] == 0).sum())}, "
            f"no_falling={int((splits_data[split]['labels'] == 1).sum())})"
        )

    # Save to disk
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(splits_data, cache_path)
    logger.info(f"Features saved successfully to {cache_path}")

    return {
        split: PatientFeatureDataset(
            splits_data[split]["cls"],
            splits_data[split]["patches"],
            splits_data[split]["labels"],
        )
        for split in ["train", "val", "test"]
    }
