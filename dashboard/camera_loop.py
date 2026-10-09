"""
HackCure — Camera Loop (Scenario A)
=====================================
Reads from a camera/video, runs the YOLO + DeepFace pipeline,
and sends structured events to the FastAPI server via REST API.

NO raw video is transmitted to the frontend.

Usage:
    python camera_loop.py                     # webcam
    python camera_loop.py --source video.mp4  # video file
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import cv2
import requests

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "computer_vision"))

from ultralytics import YOLO

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("hackcure.camera")

# ─── Configuration ─────────────────────────────────────────
SERVER_URL = "http://localhost:8000"
MODEL_PATH = str(PROJECT_ROOT / "runs" / "detect" / "runs" / "hackcure_v2" / "weights" / "best.pt")

# Fallback model paths
ALT_PATHS = [
    str(PROJECT_ROOT / "runs" / "detect" / "runs" / "hackcure_v2" / "weights" / "best.pt"),
    str(PROJECT_ROOT / "runs" / "detect" / "runs" / "hackcure_yolov8n" / "weights" / "best.pt"),
]

# DeepFace pain emotions
PAIN_EMOTIONS = {"sad", "fear", "angry", "disgust"}

# Debounce: don't send the same event type for the same patient within X seconds
DEBOUNCE_SECONDS = 3.0
last_events = {}


def find_model():
    """Find the best model weights file."""
    for path in [MODEL_PATH] + ALT_PATHS:
        if Path(path).exists():
            logger.info(f"Model found: {path}")
            return path
    logger.error("No model weights found!")
    sys.exit(1)


def init_deepface():
    """Try to import DeepFace for pain detection."""
    try:
        import warnings
        warnings.filterwarnings("ignore")
        import os
        os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
        from deepface import DeepFace
        return DeepFace
    except ImportError:
        logger.warning("DeepFace not available. Pain detection disabled.")
        return None


def analyze_pain(DeepFace, img, x1, y1, x2, y2):
    """Analyze facial expression for pain indicators."""
    if DeepFace is None:
        return False, "unknown"

    h, w = img.shape[:2]
    pad = 20
    crop = img[max(0, y1-pad):min(h, y2+pad), max(0, x1-pad):min(w, x2+pad)]

    if crop.size == 0:
        return False, "no_face"

    try:
        results = DeepFace.analyze(crop, actions=['emotion'],
                                   enforce_detection=False, silent=True)
        if isinstance(results, list):
            res = results[0]
        else:
            res = results
        emotion = res['dominant_emotion']
        return emotion in PAIN_EMOTIONS, emotion
    except Exception:
        return False, "no_face"


def send_event(patient_id, event_type, confidence):
    """Send event to the FastAPI server."""
    key = f"{patient_id}:{event_type}"
    now = time.time()

    # Debounce
    if key in last_events and (now - last_events[key]) < DEBOUNCE_SECONDS:
        return

    last_events[key] = now

    try:
        resp = requests.post(
            f"{SERVER_URL}/api/yolo/event",
            json={
                "patient_id": patient_id,
                "event_type": event_type,
                "confidence": round(confidence, 4),
            },
            timeout=2,
        )
        if resp.ok:
            logger.info(f"Event sent: {patient_id} -> {event_type}")
        else:
            logger.warning(f"Server rejected event: {resp.status_code}")
    except requests.exceptions.ConnectionError:
        logger.warning("Cannot reach server. Is it running?")
    except Exception as e:
        logger.error(f"Send error: {e}")


def main():
    parser = argparse.ArgumentParser(description="HackCure Camera Loop")
    parser.add_argument("--source", type=str, default="0",
                        help="Camera index or video path")
    parser.add_argument("--patient-id", type=str, default="patient_01",
                        help="Patient ID to associate detections with")
    parser.add_argument("--conf", type=float, default=0.3,
                        help="YOLO confidence threshold")
    args = parser.parse_args()

    # Load model
    model_path = find_model()
    model = YOLO(model_path)
    logger.info("YOLO model loaded")

    # Load DeepFace
    DeepFace = init_deepface()

    # Open camera
    source = int(args.source) if args.source.isdigit() else args.source
    cap = cv2.VideoCapture(source)

    if not cap.isOpened():
        logger.error(f"Cannot open source: {args.source}")
        sys.exit(1)

    logger.info(f"Camera opened: {args.source}")
    logger.info(f"Patient ID: {args.patient_id}")
    logger.info(f"Server: {SERVER_URL}")
    logger.info("Press Ctrl+C to stop")

    # Switch server to real mode
    try:
        requests.post(f"{SERVER_URL}/api/mode",
                      json={"mode": "real"}, timeout=2)
    except Exception:
        pass

    frame_count = 0
    try:
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            frame_count += 1

            # Process every 3rd frame for performance
            if frame_count % 3 != 0:
                continue

            # Run YOLO
            results = model(frame, conf=args.conf, verbose=False)

            if not results or len(results[0].boxes) == 0:
                continue

            for box in results[0].boxes:
                cls_id = int(box.cls[0])
                conf = float(box.conf[0])
                cls_name = model.names[cls_id]
                x1, y1, x2, y2 = map(int, box.xyxy[0])

                # Determine fall status
                is_falling = cls_name == "falling"

                # Analyze pain
                is_pain, emotion = analyze_pain(DeepFace, frame, x1, y1, x2, y2)

                # Determine event type
                if is_falling and is_pain:
                    send_event(args.patient_id, "fall_and_pain", conf)
                elif is_falling:
                    send_event(args.patient_id, "fall", conf)
                elif is_pain:
                    send_event(args.patient_id, "pain", conf)
                # If normal, send recover only if there was a previous alert
                elif f"{args.patient_id}:fall" in last_events or \
                     f"{args.patient_id}:pain" in last_events:
                    send_event(args.patient_id, "recover", conf)

    except KeyboardInterrupt:
        logger.info("Stopped by user")
    finally:
        cap.release()
        logger.info(f"Processed {frame_count} frames")


if __name__ == "__main__":
    main()
