r"""
HackCure - 2-Stage Pipeline (YOLOv8 + DeepFace)
===============================================================
Stage 1: YOLOv8 Nano detects posture (falling / no_falling)
Stage 2: DeepFace analyzes the crop for facial expressions (pain / no_pain)

Logic:
  - Emotions: sad, fear, angry, disgust -> PAIN
  - Emotions: happy, neutral, surprise  -> NO PAIN

Usage:
    python test_yolo.py                          # random test image
    python test_yolo.py "C:/path/to/image.jpg"   # custom image
"""

import os
import sys
import random
import glob
import warnings

import cv2
import numpy as np
from ultralytics import YOLO

# Suppress deepface warnings
warnings.filterwarnings("ignore")
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
try:
    from deepface import DeepFace
except ImportError:
    print("ERROR: deepface not installed. Run: pip install deepface tf-keras")
    sys.exit(1)

# ========================================================
# CONFIGURATION
# ========================================================
MODEL_PATH = r"runs\detect\runs\hackcure_v2\weights\best.pt"
# Fallback paths (searched in order)
ALT_PATHS = [
    r"runs\detect\runs\hackcure_v2\weights\best.pt",
    r"runs\hackcure_v2\weights\best.pt",
    r"runs\detect\runs\hackcure_yolov8n\weights\best.pt",
    r"runs\detect\train\weights\best.pt",
]

TEST_DIR = r"c:\Users\bousl\Desktop\hackcure_project\computer_vision\data\processed\patient_detection\images\test"
OUTPUT_PATH = r"runs\test_result.jpg"
CONFIDENCE_THRESHOLD = 0.25

COLORS = {
    "falling":     (0, 0, 255),        # RED - critical
    "no_falling":  (0, 255, 0),        # GREEN - normal
}
DEFAULT_COLOR = (200, 200, 200)

PAIN_EMOTIONS = ['sad', 'fear', 'angry', 'disgust']


def draw_fancy_box(img, x1, y1, x2, y2, color, label, thickness=2):
    cv2.rectangle(img, (x1, y1), (x2, y2), color, thickness)
    corner_len = min(20, (x2 - x1) // 4, (y2 - y1) // 4)
    cv2.line(img, (x1, y1), (x1 + corner_len, y1), color, thickness + 1)
    cv2.line(img, (x1, y1), (x1, y1 + corner_len), color, thickness + 1)
    cv2.line(img, (x2, y1), (x2 - corner_len, y1), color, thickness + 1)
    cv2.line(img, (x2, y1), (x2, y1 + corner_len), color, thickness + 1)
    cv2.line(img, (x1, y2), (x1 + corner_len, y2), color, thickness + 1)
    cv2.line(img, (x1, y2), (x1, y2 - corner_len), color, thickness + 1)
    cv2.line(img, (x2, y2), (x2 - corner_len, y2), color, thickness + 1)
    cv2.line(img, (x2, y2), (x2, y2 - corner_len), color, thickness + 1)

    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.55
    (tw, th), _ = cv2.getTextSize(label, font, font_scale, 1)
    cv2.rectangle(img, (x1, y1 - th - 10), (x1 + tw + 10, y1), color, -1)
    cv2.putText(img, label, (x1 + 5, y1 - 5), font, font_scale, (255, 255, 255), 1, cv2.LINE_AA)


def draw_alert_banner(img, text, color=(0, 0, 255)):
    h, w = img.shape[:2]
    overlay = img.copy()
    cv2.rectangle(overlay, (0, 0), (w, 45), color, -1)
    cv2.addWeighted(overlay, 0.7, img, 0.3, 0, img)
    cv2.putText(img, text, (15, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)


def analyze_pain_with_deepface(img, x1, y1, x2, y2):
    """Crops the person from the image and runs DeepFace to find expressions."""
    # Add a little padding to the crop
    h, w = img.shape[:2]
    pad = 20
    cy1, cy2 = max(0, y1 - pad), min(h, y2 + pad)
    cx1, cx2 = max(0, x1 - pad), min(w, x2 + pad)
    
    crop = img[cy1:cy2, cx1:cx2]
    
    if crop.size == 0:
        return False, "no_face", None

    try:
        try:
            # First try: strictly find a face
            results = DeepFace.analyze(crop, actions=['emotion'], enforce_detection=True, silent=True)
        except Exception:
            # Fallback: face might be hidden by hands. Try without enforcing detection
            results = DeepFace.analyze(crop, actions=['emotion'], enforce_detection=False, silent=True)
            
        if isinstance(results, list):
            res = results[0]
        else:
            res = results
            
        emotion = res['dominant_emotion']
        is_pain = emotion in PAIN_EMOTIONS
        display_emotion = "PAIN" if is_pain else emotion.upper()
        
        # Adjust face box coordinates relative to original image
        face_box = None
        if 'region' in res:
            fx = cx1 + res['region']['x']
            fy = cy1 + res['region']['y']
            fw = res['region']['w']
            fh = res['region']['h']
            face_box = [fx, fy, fx + fw, fy + fh]

        return is_pain, emotion, display_emotion, face_box
    except Exception as e:
        return False, "no_face", "NO_FACE", None


def main():
    # ========================================================
    # 1. Load YOLO model
    # ========================================================
    found = False
    for alt in ALT_PATHS:
        if os.path.exists(alt):
            print(f"Model found at: {alt}")
            model = YOLO(alt)
            found = True
            break
            
    if not found:
        print("ERROR: No trained model found!")
        print("Run train_yolo.py first.")
        return

    # ========================================================
    # 2. Pick image
    # ========================================================
    if len(sys.argv) > 1:
        random_image = sys.argv[1]
        if not os.path.exists(random_image):
            print(f"ERROR: Image not found: {random_image}")
            return
        img_name = os.path.basename(random_image)
    else:
        test_images = glob.glob(os.path.join(TEST_DIR, "*.jpg"))
        test_images += glob.glob(os.path.join(TEST_DIR, "*.png"))
        if not test_images:
            print(f"ERROR: No test images found in {TEST_DIR}")
            return
        random_image = random.choice(test_images)
        img_name = os.path.basename(random_image)
        
    print(f"\n{'=' * 60}")
    print(f"Testing on image: {img_name}")
    print(f"{'=' * 60}")

    # ========================================================
    # 3. Run YOLO inference (Stage 1)
    # ========================================================
    results = model.predict(source=random_image, conf=CONFIDENCE_THRESHOLD, verbose=False)
    img = cv2.imread(random_image)
    result = results[0]
    
    n_fallen = 0
    alerts = []
    
    if result.boxes is not None and len(result.boxes) > 0:
        for box in result.boxes:
            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
            conf = float(box.conf[0])
            cls_id = int(box.cls[0])
            cls_name = model.names[cls_id]

            if cls_name == "falling":
                n_fallen += 1
            
            # ========================================================
            # 4. Run DeepFace on crop (Stage 2)
            # ========================================================
            print(f"Analyzing face for {cls_name}...")
            is_pain, emotion, display_emotion, face_box = analyze_pain_with_deepface(img, x1, y1, x2, y2)
            
            # Draw Face Box if found
            if face_box and emotion != "no_face":
                fx1, fy1, fx2, fy2 = face_box
                face_color = (0, 165, 255) if is_pain else (255, 200, 0)
                cv2.rectangle(img, (fx1, fy1), (fx2, fy2), face_color, 2)
                cv2.putText(img, display_emotion, (fx1, fy1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, face_color, 1)

            # Draw Body Box
            display_cls = "patient" if cls_name == "no_falling" else cls_name
            color = COLORS.get(cls_name, DEFAULT_COLOR)
            label = f"{display_cls} {conf:.2f} | {display_emotion}"
            draw_fancy_box(img, x1, y1, x2, y2, color, label)
            
            # Add to alerts based on both posture and pain
            if cls_name == "falling":
                if is_pain:
                    alerts.append(("CHUTE + DOULEUR PROBABLE !", (0, 0, 255)))
                elif emotion == "no_face":
                    alerts.append(("CHUTE (Visage non visible)", (0, 0, 255)))
                else:
                    alerts.append(("CHUTE (Sans douleur visible)", (0, 165, 255)))
            elif is_pain:
                # Patient not falling (or YOLO missed the fall), but in pain
                alerts.append(("ALERTE: DOULEUR SEVERE DETECTEE", (0, 165, 255)))

    # ========================================================
    # 5. Summary & Alerts
    # ========================================================
    if alerts:
        most_critical = alerts[0]
        draw_alert_banner(img, most_critical[0], most_critical[1])
        status = "PAIN" if "DOULEUR" in most_critical[0] else "NO PAIN"
    elif n_fallen == 0:
        status = "OK"
    else:
        status = "FALLEN"
        
    summary = f"Falling: {n_fallen} | Status: {status}"
    h, w = img.shape[:2]
    cv2.putText(img, summary, (10, h - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)

    os.makedirs(os.path.dirname(OUTPUT_PATH) if os.path.dirname(OUTPUT_PATH) else ".", exist_ok=True)
    cv2.imwrite(OUTPUT_PATH, img)

    print(f"\n  === STATUS: {status} ===")
    if alerts:
        for alert_text, _ in alerts:
            print(f"    >>> {alert_text}")
    print(f"\n  Image sauvegardee: {OUTPUT_PATH}")
    
    try:
        cv2.imshow("HackCure - 2-Stage Pipeline", img)
        cv2.waitKey(0)
        cv2.destroyAllWindows()
    except Exception:
        pass


if __name__ == '__main__':
    main()
