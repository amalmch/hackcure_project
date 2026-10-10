"""
HackCure — Multi-Modal AI Camera & Monitoring Loop
===================================================
Real-time integration of:
  1. YOLOv8n spatial detection (trained patient detector)
  2. DINOv2 Vision Transformer (posture & semantic fall analysis)
  3. TemporalRiskAnalyzer (sliding-window behavior & risk fusion)
  4. InterventionAgentAdapter (clinical decision-support recommendations)
  5. REST / WebSocket bridge to 3D Hospital Dashboard (server.py)

Usage:
    python camera_loop.py                     # webcam (source 0)
    python camera_loop.py --source video.mp4  # video file
    python camera_loop.py --patient-id patient_02
"""

from __future__ import annotations
import argparse
import json
import logging
from pathlib import Path
import sys
import time
from typing import Optional, Tuple

import cv2
import numpy as np
import requests
import torch

# Paths & Imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "computer_vision"))

from ultralytics import YOLO
from src.transformer.model import HackCurePatientTransformer
from src.temporal.risk_analyzer import TemporalRiskAnalyzer
from src.temporal.agent_adapter import InterventionAgentAdapter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("hackcure.camera")

SERVER_URL = "http://localhost:8000"

# Debounce settings
DEBOUNCE_SECONDS = 2.0
last_events = {}
prev_positions = {}


def find_yolo_model() -> str:
    """Find the best trained YOLOv8n weights."""
    candidates = [
        PROJECT_ROOT / "computer_vision" / "runs" / "patient_yolov8n" / "baseline" / "weights" / "best.pt",
        PROJECT_ROOT / "runs" / "detect" / "runs" / "hackcure_v2" / "weights" / "best.pt",
        PROJECT_ROOT / "runs" / "detect" / "runs" / "hackcure_yolov8n" / "weights" / "best.pt",
        PROJECT_ROOT / "computer_vision" / "models" / "best.pt",
        Path("yolov8n.pt"),
    ]
    for p in candidates:
        if p.exists():
            logger.info(f"YOLO model found: {p}")
            return str(p)
    logger.error("No YOLO model weights found!")
    sys.exit(1)


def load_vision_transformer(device: str) -> Optional[HackCurePatientTransformer]:
    """Load the trained DINOv2 Vision Transformer."""
    weights_path = PROJECT_ROOT / "computer_vision" / "runs" / "patient_transformer" / "best_transformer.pt"
    try:
        transformer = HackCurePatientTransformer(device=device)
        if weights_path.exists():
            ckpt = torch.load(weights_path, map_location=device, weights_only=True)
            transformer.head.load_state_dict(ckpt["model_state"])
            logger.info(f"Loaded trained Vision Transformer from {weights_path}")
        else:
            logger.warning(f"Transformer weights not found at {weights_path}, using base head.")
        transformer.eval()
        return transformer
    except Exception as e:
        logger.warning(f"Could not load Vision Transformer: {e}")
        return None


def init_deepface():
    """Try to import DeepFace for facial pain/discomfort analysis."""
    try:
        import warnings
        warnings.filterwarnings("ignore")
        import os
        os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
        from deepface import DeepFace
        return DeepFace
    except ImportError:
        logger.warning("DeepFace not available. Discomfort will rely on postural cues.")
        return None


PAIN_EMOTIONS = {"sad", "fear", "angry", "disgust"}

def analyze_pain(DeepFace, img, x1, y1, x2, y2) -> Tuple[bool, str, float]:
    """Analyze facial region for observable pain cues."""
    if DeepFace is None:
        return False, "unknown", 0.0

    h, w = img.shape[:2]
    pad = 20
    crop = img[max(0, y1-pad):min(h, y2+pad), max(0, x1-pad):min(w, x2+pad)]
    if crop.size == 0:
        return False, "no_face", 0.0

    try:
        # Use opencv backend for faster execution
        results = DeepFace.analyze(crop, actions=['emotion'], enforce_detection=False, detector_backend='opencv', silent=True)
        res = results[0] if isinstance(results, list) else results
        emotion = res.get('dominant_emotion', 'neutral')
        score = float(res.get('emotion', {}).get(emotion, 50.0)) / 100.0
        return emotion in PAIN_EMOTIONS, emotion, score
    except Exception:
        return False, "no_face", 0.0


def send_structured_event(event_data: dict) -> None:
    """Send structured event to the FastAPI backend (which broadcasts to 3D simulation)."""
    patient_id = event_data["patient_id"]
    event_type = event_data["event_type"]
    key = f"{patient_id}:{event_type}"
    now = time.time()

    # Debounce for non-critical events
    if event_type != "fall" and key in last_events and (now - last_events[key]) < DEBOUNCE_SECONDS:
        return

    last_events[key] = now

    payload = {
        "patient_id": patient_id,
        "event_type": event_type,
        "confidence": event_data.get("confidence", 0.9),
        "risk_level": event_data.get("risk_level", "low"),
        "risk_score": event_data.get("risk_score", 0.0),
        "behavior_indicators": event_data.get("evidence", []),
        "recommendations": event_data.get("recommendations", []),
    }

    try:
        resp = requests.post(f"{SERVER_URL}/api/yolo/event", json=payload, timeout=1.5)
        if resp.ok:
            logger.info(
                f"[EVENT BROADCAST] {patient_id} -> {event_type} "
                f"(Risk: {payload['risk_level'].upper()} {payload['risk_score']:.2f})"
            )
        else:
            logger.warning(f"Server rejected event: {resp.status_code}")
    except requests.exceptions.ConnectionError:
        logger.warning("Cannot reach server at http://localhost:8000. Is it running?")
    except Exception as e:
        logger.error(f"Send error: {e}")


def main():
    parser = argparse.ArgumentParser(description="HackCure Multi-Modal AI Camera Loop")
    parser.add_argument("--source", type=str, default="0", help="Camera index or video file path")
    parser.add_argument("--patient-id", type=str, default="patient_01", help="Patient ID to associate detections with")
    parser.add_argument("--conf", type=float, default=0.25, help="YOLO confidence threshold")
    parser.add_argument("--display", action="store_true", default=True, help="Show annotated OpenCV window")
    args = parser.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info(f"Running on hardware: {device.upper()}")

    # 1. Load Models
    yolo_model_path = find_yolo_model()
    yolo = YOLO(yolo_model_path)
    logger.info("YOLOv8n model ready.")

    transformer = load_vision_transformer(device)
    risk_analyzer = TemporalRiskAnalyzer(window_size=30)
    agent_adapter = InterventionAgentAdapter()
    DeepFace = init_deepface()

    # 2. Open Camera
    source = int(args.source) if args.source.isdigit() else args.source
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        logger.error(f"Cannot open video source: {args.source}")
        sys.exit(1)

    logger.info(f"Video source active: {args.source}")
    logger.info(f"Assigned Patient: {args.patient_id}")
    logger.info("Connecting to 3D Dashboard server...")

    # Switch server to real mode
    try:
        requests.post(f"{SERVER_URL}/api/mode", json={"mode": "real"}, timeout=2)
    except Exception:
        pass

    frame_count = 0
    process_every_n_frames = 10
    
    # State for drawing HUD on skipped frames
    last_x1, last_y1, last_x2, last_y2 = 0, 0, 0, 0
    last_cls_name = "person"
    last_conf = 0.0
    last_fall_prob = 0.0
    last_event_payload = {}
    
    try:
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            frame_count += 1
            h_img, w_img = frame.shape[:2]
            diag = np.sqrt(h_img**2 + w_img**2)

            # Process AI every N frames for responsive throughput
            if frame_count % process_every_n_frames != 0:
                if args.display:
                    # Draw cached bounding box
                    if last_x2 > 0:
                        risk_lvl = last_event_payload.get("risk_level", "low").upper()
                        color = (0, 255, 0) if risk_lvl == "LOW" else (0, 215, 255) if risk_lvl == "MODERATE" else (0, 140, 255) if risk_lvl == "HIGH" else (0, 0, 255)
                        cv2.rectangle(frame, (last_x1, last_y1), (last_x2, last_y2), color, 2)
                        
                        hud_text_1 = f"YOLO: {last_cls_name} ({last_conf:.0%}) | ViT Fall Prob: {last_fall_prob:.0%}"
                        hud_text_2 = f"Risk: {risk_lvl} ({last_event_payload.get('risk_score', 0):.2f}) | Evidence: {','.join(last_event_payload.get('evidence', [])) or 'None'}"
                        cv2.putText(frame, hud_text_1, (last_x1, max(20, last_y1 - 25)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
                        cv2.putText(frame, hud_text_2, (last_x1, max(40, last_y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (255, 255, 255), 1)

                    cv2.imshow("HackCure AI Pipeline", frame)
                    if cv2.waitKey(1) & 0xFF == 27:
                        break
                continue

            # Step 1: YOLO Detection
            results = yolo(frame, conf=args.conf, verbose=False)
            if not results or len(results[0].boxes) == 0:
                last_x2 = 0 # reset box
                if args.display:
                    cv2.imshow("HackCure AI Pipeline", frame)
                    if cv2.waitKey(1) & 0xFF == 27:
                        break
                continue

            # Select largest detected patient
            boxes = results[0].boxes
            best_box = max(boxes, key=lambda b: float((b.xyxy[0][2] - b.xyxy[0][0]) * (b.xyxy[0][3] - b.xyxy[0][1])))

            cls_id = int(best_box.cls[0])
            conf = float(best_box.conf[0])
            cls_name = yolo.names.get(cls_id, "person")
            x1, y1, x2, y2 = map(int, best_box.xyxy[0])
            cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0

            # Compute velocity relative to previous frame
            prev = prev_positions.get(args.patient_id)
            if prev is not None:
                vel = np.sqrt((cx - prev[0])**2 + (cy - prev[1])**2) / max(1.0, diag)
            else:
                vel = 0.001
            prev_positions[args.patient_id] = (cx, cy)

            # Step 2: Extract Patient Crop & Vision Transformer Feature/Posture
            crop_bgr = frame[max(0, y1):min(h_img, y2), max(0, x1):min(w_img, x2)]
            trans_result = None
            fall_prob = 0.9 if cls_name == "falling" else 0.1
            posture_pred = cls_name

            if transformer is not None and crop_bgr.size > 0:
                try:
                    crop_rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
                    trans_result = transformer.predict_crop(crop_rgb)
                    fall_prob = trans_result["fall_probability"]
                    posture_pred = trans_result["class_name"]
                except Exception as e:
                    logger.debug(f"Transformer error: {e}")

            # Step 3: Facial / Posture Discomfort
            is_pain, emotion, pain_conf = analyze_pain(DeepFace, frame, x1, y1, x2, y2)
            
            # Cache results for skipped frames
            last_x1, last_y1, last_x2, last_y2 = x1, y1, x2, y2
            last_cls_name = cls_name
            last_conf = conf
            last_fall_prob = fall_prob

            # Step 4: Temporal Risk Analyzer Fusion
            risk_analyzer.update_patient(
                patient_id=args.patient_id,
                yolo_state=cls_name,
                yolo_confidence=conf,
                yolo_velocity=vel,
                transformer_posture=posture_pred,
                transformer_fall_prob=fall_prob,
                discomfort_detected=is_pain,
                discomfort_conf=pain_conf,
            )

            # Step 5: Structured Event Generation & Agent Recommendations
            event_payload = risk_analyzer.generate_event(args.patient_id)
            recs = []
            if event_payload:
                last_event_payload = event_payload.copy()
                recs = agent_adapter.request_recommendation(event_payload)
                event_payload["recommendations"] = recs
                last_event_payload["recommendations"] = recs
                send_structured_event(event_payload)

            # Step 6: OpenCV Annotation HUD
            if args.display and event_payload:
                risk_lvl = event_payload.get("risk_level", "low").upper()
                color = (0, 255, 0) if risk_lvl == "LOW" else (0, 215, 255) if risk_lvl == "MODERATE" else (0, 140, 255) if risk_lvl == "HIGH" else (0, 0, 255)

                # Draw bounding box
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

                # Labels
                hud_text_1 = f"YOLO: {cls_name} ({conf:.0%}) | ViT Fall Prob: {fall_prob:.0%}"
                hud_text_2 = f"Risk: {risk_lvl} ({event_payload['risk_score']:.2f}) | Evidence: {','.join(event_payload['evidence']) or 'None'}"
                cv2.putText(frame, hud_text_1, (x1, max(20, y1 - 25)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
                cv2.putText(frame, hud_text_2, (x1, max(40, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (255, 255, 255), 1)

                # Bottom Recommendation Banner
                if recs:
                    rec_banner = f"Agent: {recs[0]}"
                    cv2.rectangle(frame, (0, h_img - 35), (w_img, h_img), (20, 20, 20), -1)
                    cv2.putText(frame, rec_banner[:80], (10, h_img - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)

                cv2.imshow("HackCure AI Pipeline", frame)
                if cv2.waitKey(1) & 0xFF == 27:  # ESC to exit
                    break

    except KeyboardInterrupt:
        logger.info("Camera loop terminated by user.")
    finally:
        cap.release()
        cv2.destroyAllWindows()
        logger.info(f"Processed {frame_count} frames.")


if __name__ == "__main__":
    main()
