"""
HackCure - YOLOv8n Training Script (Optimized for RPi5 Deployment)
===================================================================
Trains YOLOv8 Nano for patient fall detection ONLY.

2 Classes:
  0: falling     - Person is falling or has fallen
  1: no_falling  - Person in normal state (lying, sitting, moving, out)

(Pain inference is now handled by DeepFace in test_yolo.py)

Usage:
    python train_yolo.py
"""

from ultralytics import YOLO


def main():
    # ========================================================
    # YOLOv8 NANO - lightweight for Raspberry Pi 5 deployment
    # ========================================================
    model = YOLO("yolov8n.pt")

    # Dataset path
    data_path = r"c:\Users\bousl\Desktop\hackcure_project\computer_vision\data\processed\patient_detection\data.yaml"

    print("=" * 60)
    print("HackCure - Training YOLOv8n (Nano) v2")
    print("2 classes: falling, no_falling")
    print("Target: Raspberry Pi 5 deployment")
    print("Optimized hyperparameters for MAXIMUM accuracy")
    print("=" * 60)

    # ========================================================
    # OPTIMIZED Hyperparameters - v2 (Maximum Accuracy)
    # ========================================================
    results = model.train(
        data=data_path,

        # --- Core Training ---
        epochs=150,           # More epochs = model learns better
        patience=30,          # Wait 30 epochs before early stop
        imgsz=640,            # Standard resolution
        device=0,             # GPU (CUDA)
        batch=16,             # Smaller batch = better generalization on small datasets

        # --- Optimizer (SGD better for generalization on small datasets) ---
        optimizer="SGD",
        lr0=0.01,             # Standard SGD learning rate
        lrf=0.01,             # Final LR = lr0 * lrf
        momentum=0.937,       # SGD momentum
        weight_decay=0.0005,  # L2 regularization
        warmup_epochs=5,      # Gradual warmup
        warmup_momentum=0.8,  # Warmup momentum
        cos_lr=True,          # Cosine annealing schedule

        # --- Regularization (CRITICAL for reducing confusion) ---
        dropout=0.1,          # Dropout to prevent overfitting
        label_smoothing=0.05, # Reduces overconfident wrong predictions

        # --- Augmentation (AGGRESSIVE - teaches model diverse poses) ---
        hsv_h=0.02,           # Hue variation
        hsv_s=0.7,            # Strong saturation variation
        hsv_v=0.4,            # Strong brightness variation
        degrees=15.0,         # MORE rotation (catches angled falls like stairs)
        translate=0.2,        # More translation
        scale=0.6,            # Stronger zoom in/out
        shear=3.0,            # More shear for perspective changes
        perspective=0.001,    # More perspective distortion
        fliplr=0.5,           # Horizontal flip
        flipud=0.0,           # NO vertical flip
        mosaic=1.0,           # Full mosaic augmentation
        mixup=0.1,            # More mixup for better generalization
        copy_paste=0.1,       # Copy-paste augmentation
        erasing=0.2,          # Random erasing to handle occlusion
        close_mosaic=20,      # Disable mosaic last 20 epochs

        # --- Loss weights (prioritize classification accuracy) ---
        cls=1.5,              # Higher weight on classification loss
        box=7.5,              # Standard box loss weight

        # --- Performance ---
        amp=True,             # Mixed precision
        workers=8,            # DataLoader workers
        seed=42,              # Reproducibility

        # --- Output ---
        project="runs",
        name="hackcure_v2",
        exist_ok=True,
        verbose=True,
    )

    print("\n" + "=" * 60)
    print("TRAINING v2 COMPLETE!")
    print("=" * 60)
    print(f"Best weights: runs/hackcure_v2/weights/best.pt")
    print(f"Use this for deployment on Raspberry Pi 5")


if __name__ == '__main__':
    main()
