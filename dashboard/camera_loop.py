"""
HackCure — Multi-Modal AI Camera & Monitoring Loop
===================================================
Real-time integration of:
  1. YOLOv8n spatial detection (trained patient detector)
  2. DINOv2 Vision Transformer (posture & semantic fall analysis) — OPTIONAL
  3. TemporalRiskAnalyzer (sliding-window behavior & risk fusion)
  4. InterventionAgentAdapter (clinical decision-support recommendations)
  5. REST bridge to the platform: legacy `/api/yolo/event` (3D dashboard) AND the MQTT/HTTP contracts
     (`POST /api/ingest`: vision/state + vision/expression + vision/behavior) used by the agents.

Fusion de la réécriture d'Amal (12e1eb2) et de notre version (publication au format des contrats).
Le Vision Transformer n'est utilisé que si PyTorch, le backbone DINOv2 et les poids entraînés sont déjà sur le
disque : sinon repli automatique sur YOLO + analyse temporelle, sans erreur et sans téléchargement.

Usage:
    python camera_loop.py                     # webcam (source 0)
    python camera_loop.py --source video.mp4  # video file
    python camera_loop.py --patient-id patient_02 --room 102 --server http://localhost:8010 --no-display
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

import requests

# Paths & Imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "computer_vision"))

from src.behavior import BehaviorAnalyzer  # noqa: E402  (analyse temporelle + transformer optionnel)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("hackcure.camera")

SERVER_URL = "http://localhost:8000"
ROOM = "101"

# Debounce settings
DEBOUNCE_SECONDS = 2.0
last_events: dict = {}
prev_positions: dict = {}
_last_contract = {"t": 0.0, "behavior": None, "behavior_t": 0.0}
_alert = {"active": False}


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


def init_deepface():
    """Try to import DeepFace for facial pain/discomfort analysis."""
    try:
        import os
        import warnings
        warnings.filterwarnings("ignore")
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


def contract_messages(event_data: dict, room: str, emotion: str = "unknown") -> list[dict]:
    """Messages au format des contrats (contracts/mqtt-topics.md) pour un événement de l'analyseur."""
    ts = datetime.now(timezone.utc).isoformat()
    event_type = event_data.get("event_type", "recover")
    fall = event_type in ("fall", "fall_and_pain")
    pain = event_type in ("pain", "fall_and_pain")
    conf = round(float(event_data.get("confidence", 0.9)), 3)
    state = {"ts": ts, "source": "camera_loop", "persons": 1, "patientTrackId": 1,
             "posture": "on_floor" if fall else "lying_bed", "activity": "fall" if fall else "awake_bed",
             "zone": "floor" if fall else "bed", "confidence": conf, "cvClass": "falling" if fall else "no_falling"}
    expr = "pain" if pain else ({"happy": "happy", "sad": "sad", "fear": "fear", "angry": "anger", "surprise": "surprise"}.get(emotion, "neutral"))
    msgs = [{"topic": f"hackcure/room/{room}/vision/state", "payload": state},
            {"topic": f"hackcure/room/{room}/vision/expression", "payload": {"ts": ts, "source": "camera_loop", "expression": expr, "confidence": 0.7 if pain else 0.5}}]
    level = event_data.get("behavioral_level", "low")
    indicators = list(event_data.get("evidence") or [])
    key = (level, tuple(indicators))
    now = time.time()
    if key != _last_contract["behavior"] or now - _last_contract["behavior_t"] > 15:  # sur changement, sinon toutes les 15 s
        _last_contract["behavior"], _last_contract["behavior_t"] = key, now
        msgs.append({"topic": f"hackcure/room/{room}/vision/behavior", "payload": {
            "ts": ts, "source": "camera_loop", "riskLevel": level, "riskScore": float(event_data.get("behavioral_score", 0.1)), "indicators": indicators,
            "recommendations": list(event_data.get("recommendations") or []) if level != "low" else [], "transformer": bool(event_data.get("transformer")),
            "fallProbability": event_data.get("transformer_fall_probability")}})
    return msgs


def _sign_messages(msgs: list) -> list:
    """Intégrité des trames : ajoute `seq` + `sig` (HMAC-SHA256) si EDGE_HMAC_KEY est défini ; sinon ne change rien."""
    try:
        if "signer" not in _last_contract:
            from contracts.integrity import Signer

            _last_contract["signer"] = Signer()
        signer = _last_contract["signer"]
        return [{"topic": m["topic"], "payload": signer.sign(m["topic"], m["payload"])} for m in msgs]
    except Exception:
        return msgs


def send_contract(event_data: dict, room: str, emotion: str = "unknown") -> None:
    """Publie au format des contrats (POST /api/ingest), 2 Hz max."""
    now = time.time()
    if now - _last_contract["t"] < 0.5:
        return
    _last_contract["t"] = now
    try:
        requests.post(f"{SERVER_URL}/api/ingest", json={"messages": _sign_messages(contract_messages(event_data, room, emotion))}, timeout=2)
    except Exception:
        pass


def legacy_payload(event_data: dict) -> Optional[dict]:
    """Événement pour `/api/yolo/event` (jumeau 3D), ou None s'il n'y a rien à envoyer.
    Chute et douleur sont envoyées telles quelles ; le reste est un risque comportemental ; « recover » n'est
    envoyé qu'au retour à la normale (il efface aussi les alertes en cours du patient)."""
    event_type = event_data.get("event_type", "recover")
    if event_type in ("fall", "pain", "fall_and_pain"):
        _alert["active"] = True
    elif event_data.get("behavioral_level", "low") != "low":
        event_type, _alert["active"] = "behavioral_risk", True
    elif _alert["active"]:
        event_type, _alert["active"] = "recover", False
    else:
        return None
    behavioral = event_type == "behavioral_risk"
    return {
        "patient_id": event_data["patient_id"],
        "event_type": event_type,
        "confidence": event_data.get("confidence", 0.9),
        "risk_level": event_data.get("behavioral_level") if behavioral else event_data.get("risk_level", "low"),
        "risk_score": event_data.get("behavioral_score") if behavioral else event_data.get("risk_score", 0.0),
        "behavior_indicators": event_data.get("evidence", []),
        "recommendations": event_data.get("recommendations", []),
    }


def send_structured_event(event_data: dict) -> None:
    """Send structured event to the FastAPI backend (which broadcasts to 3D simulation)."""
    payload = legacy_payload(event_data)
    if payload is None:
        return
    patient_id, event_type = payload["patient_id"], payload["event_type"]
    key = f"{patient_id}:{event_type}"
    now = time.time()

    # Debounce for non-critical events
    if event_type != "fall" and key in last_events and (now - last_events[key]) < DEBOUNCE_SECONDS:
        return

    last_events[key] = now

    try:
        resp = requests.post(f"{SERVER_URL}/api/yolo/event", json=payload, timeout=1.5)
        if resp.ok:
            logger.info(
                f"[EVENT BROADCAST] {patient_id} -> {event_type} "
                f"(Risk: {str(payload['risk_level']).upper()} {float(payload['risk_score']):.2f})"
            )
        else:
            logger.warning(f"Server rejected event: {resp.status_code}")
    except requests.exceptions.ConnectionError:
        logger.warning(f"Cannot reach server at {SERVER_URL}. Is it running?")
    except Exception as e:
        logger.error(f"Send error: {e}")


def main():
    global SERVER_URL, ROOM
    parser = argparse.ArgumentParser(description="HackCure Multi-Modal AI Camera Loop")
    parser.add_argument("--source", type=str, default="0", help="Camera index or video file path")
    parser.add_argument("--patient-id", type=str, default="patient_01", help="Patient ID to associate detections with")
    parser.add_argument("--room", type=str, default=None, help="Room code for the contract messages (default: from the patient id, patient_02 -> 102)")
    parser.add_argument("--server", type=str, default=SERVER_URL, help="Platform URL")
    parser.add_argument("--conf", type=float, default=0.25, help="YOLO confidence threshold")
    parser.add_argument("--display", action="store_true", default=True, help="Show annotated OpenCV window")
    parser.add_argument("--no-display", dest="display", action="store_false", help="Headless (no OpenCV window)")
    parser.add_argument("--no-transformer", action="store_true", help="Never load the Vision Transformer (YOLO + temporal analysis only)")
    args = parser.parse_args()
    SERVER_URL = args.server.rstrip("/")
    ROOM = args.room or ("10" + args.patient_id[-1] if args.patient_id[-1:].isdigit() else ROOM)

    import cv2
    import numpy as np
    from ultralytics import YOLO

    try:
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        device = "cpu"
    logger.info(f"Running on hardware: {device.upper()}")

    # 1. Load Models
    yolo_model_path = find_yolo_model()
    yolo = YOLO(yolo_model_path)
    logger.info("YOLOv8n model ready.")

    behavior = BehaviorAnalyzer(window_size=30, device=device, use_transformer=not args.no_transformer)
    logger.info(f"Behavior analysis mode: {behavior.mode}")
    DeepFace = init_deepface()

    # 2. Open Camera
    source = int(args.source) if args.source.isdigit() else args.source
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        logger.error(f"Cannot open video source: {args.source}")
        sys.exit(1)

    logger.info(f"Video source active: {args.source}")
    logger.info(f"Assigned Patient: {args.patient_id} (room {ROOM})")
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
    last_event_payload: dict = {}

    def risk_color(level: str):
        return (0, 255, 0) if level == "LOW" else (0, 215, 255) if level == "MODERATE" else (0, 140, 255) if level == "HIGH" else (0, 0, 255)

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
                        color = risk_color(risk_lvl)
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
                last_x2 = 0  # reset box
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

            # Step 2: Patient crop (used by the Vision Transformer when it is available)
            crop_bgr = frame[max(0, y1):min(h_img, y2), max(0, x1):min(w_img, x2)]
            crop_rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB) if (behavior.transformer is not None and crop_bgr.size > 0) else None

            # Step 3: Facial / Posture Discomfort
            is_pain, emotion, pain_conf = analyze_pain(DeepFace, frame, x1, y1, x2, y2)

            # Step 4 & 5: Temporal risk fusion, structured event, agent recommendations
            event_payload = behavior.update(args.patient_id, cls_name, conf, velocity=float(vel), crop_rgb=crop_rgb, discomfort=is_pain, discomfort_conf=pain_conf)
            fall_prob = float(event_payload.get("transformer_fall_probability", 0.9 if cls_name == "falling" else 0.1))
            recs = event_payload.get("recommendations", [])

            # Cache results for skipped frames
            last_x1, last_y1, last_x2, last_y2 = x1, y1, x2, y2
            last_cls_name = cls_name
            last_conf = conf
            last_fall_prob = fall_prob
            last_event_payload = event_payload.copy()

            send_structured_event(event_payload)        # jumeau 3D (legacy)
            send_contract(event_payload, ROOM, emotion)  # agents (contrats MQTT/HTTP)

            # Step 6: OpenCV Annotation HUD
            if args.display and event_payload:
                risk_lvl = event_payload.get("risk_level", "low").upper()
                color = risk_color(risk_lvl)

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
        if args.display:
            cv2.destroyAllWindows()
        logger.info(f"Processed {frame_count} frames.")


if __name__ == "__main__":
    main()
