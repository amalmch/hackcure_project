"""
HackCure Vision Transformer Architecture
=========================================
Multi-Head Attention and DINOv2 ViT for Patient Fall & Posture Classification.

Architecture:
  1. Backbone: DINOv2 ViT-S/14 (Frozen / feature-extracted, 384-dim latent space)
  2. Multi-Head Self-Attention layers on patch tokens
  3. Attention Pooling to aggregate spatial patch tokens
  4. Classification MLP with LayerNorm, GELU, and Dropout
  5. Classes: 0: "falling", 1: "no_falling"
"""

from __future__ import annotations
import math
import logging
from typing import Dict, Optional, Tuple, Union

import numpy as np
from PIL import Image
import torch
import torch.nn as nn
import torch.nn.functional as F
import torchvision.transforms as T

logger = logging.getLogger("hackcure.transformer")

CLASS_NAMES = {0: "falling", 1: "no_falling"}


class AttentionPooling(nn.Module):
    """
    Learned attention-based pooling over spatial patch tokens.
    Learns which body parts / image regions are informative for fall detection.
    """
    def __init__(self, dim: int):
        super().__init__()
        self.attn = nn.Linear(dim, 1)

    def forward(self, x: torch.Tensor, mask: Optional[torch.Tensor] = None) -> Tuple[torch.Tensor, torch.Tensor]:
        # x shape: (batch_size, seq_len, dim)
        scores = self.attn(x).squeeze(-1)  # (batch_size, seq_len)
        if mask is not None:
            scores = scores.masked_fill(mask, -1e4)
        weights = torch.softmax(scores, dim=-1)  # (batch_size, seq_len)
        pooled = torch.bmm(weights.unsqueeze(1), x).squeeze(1)  # (batch_size, dim)
        return pooled, weights


class TransformerClassifierHead(nn.Module):
    """
    Transformer classification head.
    Can operate on:
      - CLS token (384-dim)
      - Patch token sequence (N, 384) + CLS token via Self-Attention & Attention Pooling
    """
    def __init__(
        self,
        embed_dim: int = 384,
        num_heads: int = 6,
        num_layers: int = 2,
        mlp_dim: int = 256,
        num_classes: int = 2,
        dropout: float = 0.2,
    ):
        super().__init__()
        self.embed_dim = embed_dim
        self.num_classes = num_classes

        # Transformer encoder layers for refining spatial patch relations
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=embed_dim,
            nhead=num_heads,
            dim_feedforward=embed_dim * 2,
            dropout=dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.transformer_encoder = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)

        # Attention pooling
        self.pool = AttentionPooling(embed_dim)

        # Final MLP classifier
        self.classifier = nn.Sequential(
            nn.LayerNorm(embed_dim * 2),  # Concatenating pooled patches + CLS token
            nn.Linear(embed_dim * 2, mlp_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.LayerNorm(mlp_dim),
            nn.Linear(mlp_dim, mlp_dim // 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(mlp_dim // 2, num_classes),
        )

    def forward(
        self,
        cls_token: torch.Tensor,
        patch_tokens: Optional[torch.Tensor] = None,
    ) -> Tuple[torch.Tensor, Optional[torch.Tensor]]:
        """
        Args:
            cls_token: (B, embed_dim)
            patch_tokens: Optional (B, num_patches, embed_dim)
        Returns:
            logits: (B, num_classes)
            attention_weights: Optional (B, num_patches)
        """
        if patch_tokens is not None:
            # Process patch sequence through Transformer encoder
            refined_patches = self.transformer_encoder(patch_tokens)
            pooled_patches, attn_weights = self.pool(refined_patches)
            # Combine global CLS token + attention-weighted local patches
            features = torch.cat([cls_token, pooled_patches], dim=-1)
        else:
            # If only CLS token provided, duplicate or project
            features = torch.cat([cls_token, cls_token], dim=-1)
            attn_weights = None

        logits = self.classifier(features)
        return logits, attn_weights


class HackCurePatientTransformer(nn.Module):
    """
    End-to-end patient fall classification transformer.
    Wraps DINOv2 backbone and TransformerClassifierHead.
    """
    def __init__(
        self,
        model_size: str = "vits14",
        num_classes: int = 2,
        device: Optional[Union[str, torch.device]] = None,
    ):
        super().__init__()
        if device is not None:
            if str(device).isdigit():
                self.device = f"cuda:{device}" if torch.cuda.is_available() else "cpu"
            else:
                self.device = str(device)
        else:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.num_classes = num_classes

        # Load DINOv2 from torch hub
        logger.info(f"Loading DINOv2 {model_size} backbone...")
        self.backbone = torch.hub.load("facebookresearch/dinov2", f"dinov2_{model_size}")
        self.backbone = self.backbone.to(self.device)
        self.backbone.eval()
        for p in self.backbone.parameters():
            p.requires_grad = False  # Freeze foundation backbone

        self.embed_dim = self.backbone.embed_dim  # 384 for ViT-S
        self.head = TransformerClassifierHead(
            embed_dim=self.embed_dim,
            num_classes=num_classes,
        ).to(self.device)

        # Standard pre-processing for DINOv2 ViT
        self.transform = T.Compose([
            T.Resize((224, 224)),
            T.ToTensor(),
            T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])

    def extract_backbone_features(self, x: torch.Tensor) -> Dict[str, torch.Tensor]:
        """
        Pass image tensor through DINOv2 without gradients.
        x: (B, 3, 224, 224)
        """
        with torch.no_grad():
            feat = self.backbone.forward_features(x)
            cls_token = feat["x_norm_clstoken"]       # (B, 384)
            patch_tokens = feat["x_norm_patchtokens"] # (B, 256, 384)
        return {"cls_token": cls_token, "patch_tokens": patch_tokens}

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        End-to-end forward pass from images.
        """
        features = self.extract_backbone_features(x)
        logits, _ = self.head(features["cls_token"], features["patch_tokens"])
        return logits

    @torch.no_grad()
    def predict_crop(self, crop: Union[np.ndarray, Image.Image]) -> Dict:
        """
        High-level inference for an image crop.
        """
        self.eval()
        if isinstance(crop, np.ndarray):
            crop = Image.fromarray(crop)

        tensor = self.transform(crop).unsqueeze(0).to(self.device)
        logits = self.forward(tensor)
        probs = F.softmax(logits, dim=-1).squeeze(0).cpu().numpy()

        pred_class = int(np.argmax(probs))
        confidence = float(probs[pred_class])
        fall_prob = float(probs[0])

        return {
            "class_id": pred_class,
            "class_name": CLASS_NAMES.get(pred_class, "unknown"),
            "confidence": round(confidence, 4),
            "fall_probability": round(fall_prob, 4),
            "probabilities": {
                "falling": round(float(probs[0]), 4),
                "no_falling": round(float(probs[1]), 4),
            },
            "risk_score": round(fall_prob, 4),
            "is_pertinent_fall": fall_prob >= 0.5,
        }
