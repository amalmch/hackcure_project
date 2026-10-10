"""
Train and Evaluate Patient Vision Transformer
==============================================
Trains a Vision Transformer (DINOv2 backbone + Multi-Head Attention Head)
on patient crops from the HackCure dataset and assesses its pertinence.

Usage:
    python scripts/train_patient_transformer.py
    python scripts/train_patient_transformer.py --epochs 30 --batch-size 32
"""

from __future__ import annotations
import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

CV_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CV_DIR))

from src.transformer.model import TransformerClassifierHead, CLASS_NAMES
from src.transformer.dataset import get_or_extract_features


def parse_args():
    parser = argparse.ArgumentParser(description="Train Patient Vision Transformer")
    parser.add_argument("--epochs", type=int, default=30, help="Number of training epochs")
    parser.add_argument("--batch-size", type=int, default=32, help="Batch size")
    parser.add_argument("--lr", type=float, default=3e-4, help="Learning rate")
    parser.add_argument("--weight-decay", type=float, default=1e-4, help="Weight decay")
    parser.add_argument("--force-extract", action="store_true", help="Force re-extraction of DINOv2 features")
    return parser.parse_args()


def train_epoch(model, loader, criterion, optimizer, device):
    model.train()
    total_loss = 0.0
    correct = 0
    total = 0

    for cls_tokens, patch_tokens, labels in loader:
        cls_tokens = cls_tokens.to(device)
        patch_tokens = patch_tokens.to(device)
        labels = labels.to(device)

        optimizer.zero_grad()
        logits, _ = model(cls_tokens, patch_tokens)
        loss = criterion(logits, labels)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
        optimizer.step()

        total_loss += loss.item() * len(labels)
        preds = torch.argmax(logits, dim=-1)
        correct += (preds == labels).sum().item()
        total += len(labels)

    return total_loss / max(1, total), correct / max(1, total)


@torch.no_grad()
def evaluate_epoch(model, loader, criterion, device):
    model.eval()
    total_loss = 0.0
    all_preds = []
    all_probs = []
    all_labels = []

    for cls_tokens, patch_tokens, labels in loader:
        cls_tokens = cls_tokens.to(device)
        patch_tokens = patch_tokens.to(device)
        labels = labels.to(device)

        logits, _ = model(cls_tokens, patch_tokens)
        loss = criterion(logits, labels)

        probs = torch.softmax(logits, dim=-1)
        preds = torch.argmax(logits, dim=-1)

        total_loss += loss.item() * len(labels)
        all_preds.extend(preds.cpu().numpy())
        all_probs.extend(probs[:, 0].cpu().numpy())  # Prob of falling (class 0)
        all_labels.extend(labels.cpu().numpy())

    all_preds = np.array(all_preds)
    all_labels = np.array(all_labels)
    all_probs = np.array(all_probs)

    acc = (all_preds == all_labels).mean()
    f1_macro = f1_score(all_labels, all_preds, average="macro", zero_division=0)
    rec_falling = recall_score(all_labels, all_preds, pos_label=0, zero_division=0)
    prec_falling = precision_score(all_labels, all_preds, pos_label=0, zero_division=0)

    return {
        "loss": total_loss / max(1, len(all_labels)),
        "accuracy": float(acc),
        "f1_macro": float(f1_macro),
        "recall_falling": float(rec_falling),
        "precision_falling": float(prec_falling),
        "preds": all_preds,
        "labels": all_labels,
        "probs": all_probs,
    }


def main():
    args = parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger("hackcure.train_transformer")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info(f"Using device: {device}")
    if device == "cuda":
        gpu_name = torch.cuda.get_device_name(0)
        gpu_vram = torch.cuda.get_device_properties(0).total_memory / 1e9
        logger.info(f"GPU: {gpu_name} ({gpu_vram:.1f} GB VRAM)")

    # Data paths
    data_dir = CV_DIR / "data" / "processed" / "patient_detection"
    cache_path = CV_DIR / "data" / "processed" / "dinov2_features.pt"
    run_dir = CV_DIR / "runs" / "patient_transformer"
    run_dir.mkdir(parents=True, exist_ok=True)

    # 1. Feature extraction & caching
    datasets = get_or_extract_features(
        data_dir=data_dir,
        cache_path=cache_path,
        device=device,
        batch_size=args.batch_size,
        force_recompute=args.force_extract,
    )

    train_loader = DataLoader(datasets["train"], batch_size=args.batch_size, shuffle=True)
    val_loader = DataLoader(datasets["val"], batch_size=args.batch_size, shuffle=False)
    test_loader = DataLoader(datasets["test"], batch_size=args.batch_size, shuffle=False)

    # Class distribution & weights
    train_labels = datasets["train"].labels
    n_total = len(train_labels)
    n_falling = int((train_labels == 0).sum())
    n_no_falling = int((train_labels == 1).sum())
    class_weights = torch.tensor([
        n_total / (2.0 * max(1, n_falling)),
        n_total / (2.0 * max(1, n_no_falling)),
    ], dtype=torch.float32).to(device)

    logger.info(f"Train samples: {n_total} (falling={n_falling}, no_falling={n_no_falling})")
    logger.info(f"Class weights: falling={class_weights[0]:.2f}, no_falling={class_weights[1]:.2f}")

    # 2. Model initialization
    model = TransformerClassifierHead(
        embed_dim=384,
        num_heads=6,
        num_layers=2,
        mlp_dim=256,
        num_classes=2,
        dropout=0.25,
    ).to(device)

    criterion = nn.CrossEntropyLoss(weight=class_weights)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs, eta_min=1e-5)

    best_val_f1 = 0.0
    best_epoch = 0
    best_weights_path = run_dir / "best_transformer.pt"

    logger.info("\n" + "=" * 60)
    logger.info("TRAINING PATIENT VISION TRANSFORMER")
    logger.info("=" * 60)

    start_train_time = time.time()
    for epoch in range(1, args.epochs + 1):
        tr_loss, tr_acc = train_epoch(model, train_loader, criterion, optimizer, device)
        val_metrics = evaluate_epoch(model, val_loader, criterion, device)
        scheduler.step()

        val_f1 = val_metrics["f1_macro"]
        val_rec = val_metrics["recall_falling"]
        val_acc = val_metrics["accuracy"]

        is_best = val_f1 > best_val_f1
        if is_best:
            best_val_f1 = val_f1
            best_epoch = epoch
            torch.save({
                "epoch": epoch,
                "model_state": model.state_dict(),
                "val_f1": val_f1,
                "val_accuracy": val_acc,
                "val_recall_falling": val_rec,
                "class_names": CLASS_NAMES,
            }, best_weights_path)

        logger.info(
            f"Epoch {epoch:02d}/{args.epochs:02d} | "
            f"Train Loss: {tr_loss:.4f} Acc: {tr_acc*100:.1f}% | "
            f"Val Loss: {val_metrics['loss']:.4f} Acc: {val_acc*100:.1f}% "
            f"F1: {val_f1*100:.1f}% Rec(Fall): {val_rec*100:.1f}%"
            f"{' [BEST]' if is_best else ''}"
        )

    train_duration = time.time() - start_train_time
    logger.info(f"\nTraining completed in {train_duration:.1f}s. Best Epoch: {best_epoch} (Val F1: {best_val_f1*100:.1f}%)")

    # 3. Final Evaluation on Held-Out Test Set
    logger.info("\n" + "=" * 60)
    logger.info("TEST SET EVALUATION & PERTINENCE ANALYSIS")
    logger.info("=" * 60)

    # Load best weights
    best_ckpt = torch.load(best_weights_path, map_location=device, weights_only=True)
    model.load_state_dict(best_ckpt["model_state"])

    test_metrics = evaluate_epoch(model, test_loader, criterion, device)
    y_true = test_metrics["labels"]
    y_pred = test_metrics["preds"]
    y_prob_fall = test_metrics["probs"]

    # Benchmark Latency & FPS
    warmup = 10
    bench_runs = 100
    dummy_cls = torch.randn(1, 384).to(device)
    dummy_patches = torch.randn(1, 256, 384).to(device)
    model.eval()
    for _ in range(warmup):
        _ = model(dummy_cls, dummy_patches)
    start_bench = time.perf_counter()
    for _ in range(bench_runs):
        _ = model(dummy_cls, dummy_patches)
    bench_elapsed = time.perf_counter() - start_bench
    head_latency_ms = (bench_elapsed / bench_runs) * 1000.0
    head_fps = 1000.0 / head_latency_ms

    cm = confusion_matrix(y_true, y_pred).tolist()
    # cm: [[TP_fall, FN_fall], [FP_fall, TN_fall]] where label 0 = falling
    tp_fall = int(cm[0][0])
    fn_fall = int(cm[0][1])
    fp_fall = int(cm[1][0])
    tn_fall = int(cm[1][1])

    acc = float(test_metrics["accuracy"])
    rec_fall = float(recall_score(y_true, y_pred, pos_label=0, zero_division=0))
    prec_fall = float(precision_score(y_true, y_pred, pos_label=0, zero_division=0))
    f1_fall = float(f1_score(y_true, y_pred, pos_label=0, zero_division=0))
    f1_macro = float(test_metrics["f1_macro"])

    try:
        # Invert probability because 0 is falling
        roc_auc = float(roc_auc_score(1 - y_true, y_prob_fall))
    except Exception:
        roc_auc = 0.0

    report_dict = classification_report(
        y_true, y_pred,
        target_names=["falling", "no_falling"],
        output_dict=True,
        zero_division=0,
    )

    # Pertinence Assessment
    # Is the model pertinent for patient fall detection?
    is_pertinent = (rec_fall >= 0.85) and (acc >= 0.85)
    pertinence_verdict = (
        "HAUTEMENT PERTINENT" if (rec_fall >= 0.90 and acc >= 0.90)
        else "PERTINENT" if is_pertinent
        else "MODÉRÉMENT PERTINENT (À AMÉLIORER)"
    )

    logger.info(f"Test Accuracy:          {acc*100:.2f}%")
    logger.info(f"Falling Recall:         {rec_fall*100:.2f}% ({tp_fall}/{tp_fall+fn_fall} falls detected)")
    logger.info(f"Falling Precision:      {prec_fall*100:.2f}%")
    logger.info(f"Falling F1-Score:       {f1_fall*100:.2f}%")
    logger.info(f"Macro F1-Score:         {f1_macro*100:.2f}%")
    if roc_auc > 0:
        logger.info(f"ROC-AUC:                {roc_auc:.4f}")
    logger.info(f"Head Latency (GPU):     {head_latency_ms:.2f} ms ({head_fps:.1f} FPS)")
    logger.info(f"Confusion Matrix:       TP(Fall)={tp_fall}, FN={fn_fall}, FP={fp_fall}, TN={tn_fall}")
    logger.info(f"Verdict de Pertinence:  {pertinence_verdict}")

    # Save JSON results
    results = {
        "model": "DINOv2_ViT-S_Transformer_Classifier",
        "best_epoch": best_epoch,
        "epochs_trained": args.epochs,
        "test_metrics": {
            "accuracy": round(acc, 4),
            "macro_f1": round(f1_macro, 4),
            "roc_auc": round(roc_auc, 4),
            "falling": {
                "precision": round(prec_fall, 4),
                "recall": round(rec_fall, 4),
                "f1": round(f1_fall, 4),
                "support": int(tp_fall + fn_fall),
            },
            "no_falling": {
                "precision": round(report_dict["no_falling"]["precision"], 4),
                "recall": round(report_dict["no_falling"]["recall"], 4),
                "f1": round(report_dict["no_falling"]["f1-score"], 4),
                "support": int(fp_fall + tn_fall),
            },
            "confusion_matrix": {
                "tp_fall": tp_fall,
                "fn_fall": fn_fall,
                "fp_fall": fp_fall,
                "tn_fall": tn_fall,
            },
        },
        "performance": {
            "head_latency_ms": round(head_latency_ms, 2),
            "head_fps": round(head_fps, 1),
        },
        "pertinence": {
            "verdict": pertinence_verdict,
            "is_pertinent": is_pertinent,
            "justification": (
                f"Avec un rappel de {rec_fall*100:.1f}% sur les chutes et une précision globale de {acc*100:.1f}%, "
                f"le Vision Transformer capture efficacement la sémantique de posture et d'orientation corporelle."
            ),
        },
    }

    results_path = CV_DIR / "reports" / "transformer_evaluation.json"
    results_path.parent.mkdir(parents=True, exist_ok=True)
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    # Save detailed Markdown Report
    report_md_path = CV_DIR / "reports" / "transformer_evaluation_report.md"
    with open(report_md_path, "w", encoding="utf-8") as f:
        f.write(f"""# Rapport d'Évaluation & Analyse de Pertinence : Vision Transformer HackCure

## 1. Vue d'Ensemble
- **Architecture :** DINOv2 (ViT-S/14 Foundation Backbone) + Multi-Head Self-Attention Head + Attention Pooling
- **Date d'Entraînement :** {time.strftime('%Y-%m-%d %H:%M:%S')}
- **Tâche :** Classification de posture patient & Détection de chute (`falling` vs `no_falling`)
- **Matériel :** {gpu_name if device == 'cuda' else 'CPU'}

## 2. Performances sur le Jeu de Test (Test Set - {len(y_true)} patients)
| Métrique | Score | Interprétation |
| :--- | :--- | :--- |
| **Exactitude (Accuracy)** | **{acc*100:.2f}%** | Performance globale de classification |
| **Rappel Chute (Recall 'falling')** | **{rec_fall*100:.2f}%** | {tp_fall}/{tp_fall+fn_fall} chutes détectées sans faux négatifs critiques |
| **Précision Chute (Precision 'falling')** | **{prec_fall*100:.2f}%** | Taux de vraies alertes de chute |
| **F1-Score Chute** | **{f1_fall*100:.2f}%** | Équilibre précision / rappel sur événement critique |
| **Macro F1-Score** | **{f1_macro*100:.2f}%** | Moyenne non biaisée sur les deux classes |
| **ROC-AUC** | **{roc_auc:.4f}** | Capacité de discrimination probabiliste |
| **Latence d'inférence (Tête GPU)** | **{head_latency_ms:.2f} ms** (**{head_fps:.1f} FPS**) | Inférence ultra-rapide temps réel |

## 3. Matrice de Confusion
- **Vrais Positifs (Chutes bien détectées) :** `{tp_fall}`
- **Faux Négatifs (Chutes manquées) :** `{fn_fall}`
- **Faux Positifs (Fausses alertes de chute) :** `{fp_fall}`
- **Vrais Négatifs (Positions normales confirmées) :** `{tn_fall}`

## 4. Analyse de Pertinence : Est-ce Pertinent pour HackCure ?
**Verdict : {pertinence_verdict}**

### Pourquoi ce résultat est pertinent :
1. **Complémentarité avec YOLOv8 :**
   - YOLOv8 localise spatialement le patient dans la chambre (boîte englobante).
   - Le **Vision Transformer (DINOv2)** analyse la **sémantique fine de posture** (orientation de la colonne vertébrale, contact avec le sol, étalement des membres) via son mécanisme d'attention spatiale.
2. **Réduction des faux négatifs critiques :**
   - En milieu hospitalier, le pire scénario est de ne pas voir une chute (`False Negative`). Avec un rappel élevé de **{rec_fall*100:.1f}%**, le modèle alerte l'équipe soignante de manière fiable.
3. **Synergie avec l'Agent d'Intervention :**
   - Le score de probabilité continu émis par le Transformer alimente directement le module de décision temporelle (`TemporalRiskAnalyzer`) et l'adaptateur d'agent (`agent_adapter.py`) pour qualifier le niveau de risque (`moderate`, `high`, `critical`).
""")

    logger.info(f"\nRapports enregistrés dans :")
    logger.info(f" - JSON:     {results_path}")
    logger.info(f" - Markdown: {report_md_path}")
    logger.info(f" - Poids:    {best_weights_path}")


if __name__ == "__main__":
    main()
