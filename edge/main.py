"""
Edge Raspberry Pi 5 — chambre 101.

    python edge/main.py                       # config edge/config/room101.yaml, caméra réelle, repli auto des modèles
    python edge/main.py --fake --server http://localhost:8000     # sur PC, sans matériel ni modèle
    python edge/main.py --source video.mp4 --no-thermal --broker 192.168.1.10

Boucle : caméra → pipeline (PatientMonitor de computer_vision/src, ou pose, ou synthétique) → zones (hystérésis)
→ posture_map → publication MQTT (repli HTTP + file hors ligne). Règles locales (buzzer, veilleuse, climat)
même sans réseau. Aperçu MJPEG flouté optionnel (--stream-port). Aucune image n'est envoyée au serveur.
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from edge.actuators import Actuators  # noqa: E402
from edge.safety.local_rules import LocalRules  # noqa: E402
from edge.sensors import DHT22, DigitalInput  # noqa: E402
from edge.thermal.mlx90640 import ThermalCamera  # noqa: E402
from edge.transport import build_transport  # noqa: E402
from edge.vision.behavior import BehaviorPublisher, build_behavior  # noqa: E402
from edge.vision.expression import ExpressionEstimator  # noqa: E402
from edge.vision.persons import PersonTracker  # noqa: E402
from edge.vision.pipeline import FrameResult, build_pipeline  # noqa: E402
from edge.vision.posture_map import map_to_contract  # noqa: E402
from edge.vision.zones import ZoneTracker  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("edge.main")


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_config(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class MjpegServer:
    """Aperçu basse résolution flouté sur http://<pi>:<port>/stream (réservé au relais serveur)."""

    def __init__(self, port: int):
        self.port = port
        self.frame: Optional[bytes] = None
        self.lock = threading.Lock()
        if port:
            threading.Thread(target=self._serve, daemon=True).start()

    def update(self, frame: np.ndarray) -> None:
        try:
            import cv2

            small = cv2.resize(frame, (320, 240))
            blurred = cv2.GaussianBlur(small, (31, 31), 0)
            ok, jpg = cv2.imencode(".jpg", blurred, [int(cv2.IMWRITE_JPEG_QUALITY), 55])
            if ok:
                with self.lock:
                    self.frame = jpg.tobytes()
        except Exception:
            pass

    def _serve(self) -> None:
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        srv = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # silencieux
                pass

            def do_GET(self):
                if self.path != "/stream":
                    self.send_response(404); self.end_headers(); return
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.end_headers()
                try:
                    while True:
                        with srv.lock:
                            f = srv.frame
                        if f:
                            self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + f + b"\r\n")
                        time.sleep(0.2)
                except Exception:
                    return

        ThreadingHTTPServer(("0.0.0.0", self.port), H).serve_forever()


class Edge:
    def __init__(self, cfg: dict[str, Any], args: argparse.Namespace):
        self.cfg = cfg
        self.room = str(args.room or cfg.get("room", "101"))
        self.pipeline = build_pipeline(cfg, fake=args.fake)
        self.source = self.pipeline.mode
        # --server sans --broker : HTTP seulement (pas d'attente du broker de la config)
        if args.server and not args.broker:
            cfg.setdefault("mqtt", {})["host"] = ""
        self.transport, self.transport_kind = build_transport(cfg, self.room, broker=args.broker, server=args.server)
        logger.info("Transport : %s · vision : %s", self.transport_kind, self.source)
        z = cfg.get("zones", {})
        self.zones = ZoneTracker({k: v for k, v in z.items() if isinstance(v, list)}, float(z.get("hysteresis_s", 2.0)))
        self.persons = PersonTracker(z.get("bed", []))
        self.behavior = BehaviorPublisher(build_behavior(cfg), self.room)  # optionnel : sans effet si indisponible
        self.expression = ExpressionEstimator(cfg.get("expression", {}).get("model"), float(cfg.get("expression", {}).get("every_s", 3.0)))
        th = cfg.get("thermal", {})
        self.thermal = ThermalCamera(enabled=th.get("enabled", True) and not args.no_thermal, i2c_address=int(th.get("i2c_address", 0x33)), refresh_hz=int(th.get("refresh_hz", 4)),
                                     calibration_offset_c=float(th.get("calibration_offset_c", 0.0)), calibration_file=th.get("calibration_file"))
        self.actuators = Actuators(cfg.get("actuators", {}))
        self.rules = LocalRules(self.actuators, self._publish_critical, self.room, cfg.get("rules", {}), source=self.source)
        s = cfg.get("sensors", {})
        self.dht = DHT22(int(s.get("dht22_pin", 4)))
        self.call_btn = DigitalInput(int(s.get("call_button_pin", 22)), "bouton d'appel")
        self.door = DigitalInput(int(s.get("door_contact_pin", 5)), "contact de porte", pull_up=True)
        self.env_every = float(s.get("env_every_s", 5.0))
        self.vision_period = 1.0 / float(cfg.get("publish", {}).get("vision_hz", 2.0))
        self.thermal_period = 1.0 / float(cfg.get("publish", {}).get("thermal_hz", 1.0))
        self.sleeping_after = float(cfg.get("posture", {}).get("sleeping_after_s", 300))
        self.still_px = float(cfg.get("posture", {}).get("stillness_px", 12))
        self.stream = MjpegServer(int(args.stream_port if args.stream_port is not None else cfg.get("camera", {}).get("stream_port", 0)))
        self.show = args.show
        self._next = {"vision": 0.0, "thermal": 0.0, "env": 0.0}
        self.state = ("lying_bed", "awake_bed", "bed")
        self.last_center: Optional[tuple[float, float]] = None
        self.still_since = time.time()
        self.last_bbox_norm: Optional[tuple[float, float, float, float]] = None
        self.transport.start_command_polling(self._on_command, self._ack)

    # ── transport ───────────────────────────────────────────────────────────
    def _publish(self, topic: str, payload: dict[str, Any], critical: bool = False) -> None:
        self.transport.publish(topic, payload, critical=critical)

    def _publish_critical(self, topic: str, payload: dict[str, Any]) -> None:
        self._publish(topic, payload, critical=True)

    def _on_command(self, equipment: str, action: str, value: Any, requested_by: str, command_id: Optional[str]):
        ok, state, err = self.rules.on_command(equipment, action, value, requested_by)
        logger.info("cmd %s %s par %s → %s %s", equipment, action, requested_by, "ok" if ok else "refus", err or state)
        return ok, state, err

    def _ack(self, equipment: str, action: str, ok: bool, state: str, command_id: Optional[str], error: Optional[str] = None) -> None:
        self._publish(f"hackcure/room/{self.room}/cmd/ack", {"ts": iso_now(), "source": self.source, "equipment": equipment, "action": action, "ok": ok, "state": state, "commandId": command_id, "error": error}, critical=True)

    # ── boucle ──────────────────────────────────────────────────────────────
    def handle_frame(self, frame: np.ndarray, ts: float) -> FrameResult:
        res = self.pipeline.process(frame, ts)
        w, h = res.width, res.height
        for ev in self.persons.update(res.tracks, w, h, ts):
            payload = {"ts": iso_now(), "source": self.source, "event": ev.event, "persons": ev.persons}
            if ev.duration_s is not None:
                payload["durationSec"] = ev.duration_s
            self._publish(f"hackcure/room/{self.room}/vision/staff", payload, critical=True)
            logger.info("%s (%d personnes)", ev.event, ev.persons)
        patient = self.persons.patient_track(res.tracks, w, h)
        test_pt = None
        cv_class, conf, fall, disc = None, 0.0, False, False
        if patient:
            test_pt = patient.hips(w, h) if self.cfg.get("zones", {}).get("bed_test_point") == "hips" else None
            test_pt = test_pt or patient.bottom_center(w, h)
            cv_class, conf = patient.cls, patient.conf
            fall = res.fall_confirmed.get(patient.track_id, False)
            disc = res.discomfort.get(patient.track_id, False)
            self.last_bbox_norm = (patient.bbox[0] / w, patient.bbox[1] / h, patient.bbox[2] / w, patient.bbox[3] / h)
            c = ((patient.bbox[0] + patient.bbox[2]) / 2, (patient.bbox[1] + patient.bbox[3]) / 2)
            moving = bool(self.last_center and (abs(c[0] - self.last_center[0]) + abs(c[1] - self.last_center[1])) > self.still_px)
            if moving:
                self.still_since = ts
            self.last_center = c
        else:
            moving = False
        zone = self.zones.update(test_pt, ts)
        st = map_to_contract(cv_class, zone, fall_confirmed=fall, still_seconds=ts - self.still_since, last_zone=self.zones.last_known, moving=moving, sleeping_after_s=self.sleeping_after)
        if patient:
            beh = self.behavior.step(frame, patient.bbox, cv_class or st.posture, float(conf), disc, st.posture in ("lying_bed", "sitting_bed"), ts)
            if beh:
                self._publish(f"hackcure/room/{self.room}/vision/behavior", {"ts": iso_now(), "source": self.source, **beh})
        new = st.as_tuple()
        if new != self.state:
            self.on_transition(self.state, new, ts)
            self.state = new
        if ts >= self._next["vision"]:
            self._next["vision"] = ts + self.vision_period
            self._publish(f"hackcure/room/{self.room}/vision/state", {
                "ts": iso_now(), "source": self.source, "persons": self.persons.persons if self.persons.persons else len(res.tracks),
                "patientTrackId": patient.track_id if patient else None, "posture": st.posture, "activity": st.activity, "zone": st.zone,
                "confidence": round(float(conf), 3), "cvClass": cv_class, "floorPos": ({"x": round(test_pt[0], 3), "y": round(test_pt[1], 3)} if test_pt and st.zone != "bed" else None),
            }, critical=(st.activity == "fall"))
            if patient:
                expr, econf = self.expression.estimate(frame, patient.bbox, discomfort_hint=disc or (cv_class == "possible_discomfort"), now=ts)
                self._publish(f"hackcure/room/{self.room}/vision/expression", {"ts": iso_now(), "source": self.source, "expression": expr, "confidence": econf})
        if ts >= self._next["thermal"] and self.thermal.enabled:
            self._next["thermal"] = ts + self.thermal_period
            skin, mx = self.thermal.head_temperature(self.last_bbox_norm)
            self._publish(f"hackcure/room/{self.room}/thermal", {"ts": iso_now(), "source": self.thermal.source if self.thermal.simulated else self.source, "skinTempC": max(20.0, min(45.0, skin)), "maxTempC": mx, "calibrated": self.thermal.calibrated})
        if ts >= self._next["env"]:
            self._next["env"] = ts + self.env_every
            t, hum = self.dht.read()
            self._publish(f"hackcure/room/{self.room}/env", {"ts": iso_now(), "source": self.source if not self.dht.simulated else "sim", "tempC": t, "humidity": hum, "motion": moving, "doorOpen": self.door.is_active})
            self.rules.on_env(t, ts)
        if self.call_btn.consume_press():
            self._publish(f"hackcure/room/{self.room}/call", {"ts": iso_now(), "source": self.source, "pressed": True}, critical=True)
            self.rules.on_call(ts)
        self.transport.flush()
        if self.stream.port:
            self.stream.update(frame)
        return res

    def on_transition(self, prev: tuple[str, str, str], new: tuple[str, str, str], ts: float) -> None:
        logger.info("état %s/%s/%s → %s/%s/%s", *prev, *new)
        if new[1] == "fall":
            self.rules.on_fall(ts)
        elif prev[0] in ("lying_bed", "sitting_bed") and new[0] in ("sitting_chair", "standing", "walking", "absent"):
            self.rules.on_bed_exit(ts)
        elif new[0] in ("lying_bed", "sitting_bed") and prev[0] not in ("lying_bed", "sitting_bed"):
            self.rules.on_back_in_bed(ts)

    def run(self, source: Any, process_every: int = 2) -> None:
        cap = None
        cv2 = None
        if self.pipeline.mode != "edge-fake":
            try:
                import cv2  # type: ignore
            except ImportError:
                logger.error("OpenCV absent : passage en mode synthétique (pip install opencv-python-headless)")
                from edge.vision.pipeline import FakePipeline

                self.pipeline = FakePipeline()
                self.source = self.pipeline.mode
        if cv2 is not None and self.pipeline.mode != "edge-fake":
            cap = cv2.VideoCapture(source)
            if not cap.isOpened():
                logger.error("Source vidéo illisible : %s → passage en mode synthétique", source)
                from edge.vision.pipeline import FakePipeline

                self.pipeline = FakePipeline()
                self.source = self.pipeline.mode
                cap = None
        blank = np.zeros((480, 640, 3), dtype=np.uint8)
        i = 0
        logger.info("Edge chambre %s démarré (%s). Ctrl+C pour arrêter.", self.room, self.source)
        try:
            while True:
                if cap is not None:
                    ok, frame = cap.read()
                    if not ok:
                        logger.warning("Fin de flux / caméra perdue, nouvel essai dans 2 s")
                        time.sleep(2)
                        cap.release()
                        cap = cv2.VideoCapture(source)
                        continue
                    i += 1
                    if i % max(1, process_every):
                        continue
                else:
                    frame = blank
                    time.sleep(0.25)
                ts = time.time()
                res = self.handle_frame(frame, ts)
                if self.show and cap is not None and cv2 is not None:
                    for t in res.tracks:
                        x1, y1, x2, y2 = map(int, t.bbox)
                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                        cv2.putText(frame, f"{t.track_id}:{t.cls}", (x1, y1 - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                    cv2.putText(frame, "/".join(self.state), (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2)
                    cv2.imshow("HackCure edge", frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
        except KeyboardInterrupt:
            pass
        finally:
            if cap is not None:
                cap.release()
            self.transport.stop()


def main() -> None:
    ap = argparse.ArgumentParser(description="HackCure — edge Raspberry Pi 5 (chambre 101)")
    ap.add_argument("--config", default=str(Path(__file__).parent / "config" / "room101.yaml"))
    ap.add_argument("--source", default=None, help="index caméra / fichier vidéo / URL (défaut : config)")
    ap.add_argument("--fake", action="store_true", help="états synthétiques, sans caméra ni modèle")
    ap.add_argument("--no-thermal", action="store_true")
    ap.add_argument("--broker", default=None, help="hôte MQTT (prioritaire sur la config)")
    ap.add_argument("--server", default=None, help="URL du serveur (repli HTTP)")
    ap.add_argument("--room", default=None)
    ap.add_argument("--stream-port", type=int, default=None, help="port de l'aperçu MJPEG flouté (0 = off)")
    ap.add_argument("--show", action="store_true", help="fenêtre OpenCV de debug")
    args = ap.parse_args()
    cfg = load_config(Path(args.config))
    edge = Edge(cfg, args)
    src = args.source if args.source is not None else cfg.get("camera", {}).get("source", 0)
    if isinstance(src, str) and src.isdigit():
        src = int(src)
    edge.run(src, int(cfg.get("camera", {}).get("process_every", 2)))


if __name__ == "__main__":
    main()
