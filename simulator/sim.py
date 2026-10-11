"""
Simulateur autonome (processus séparé du serveur).

    python simulator/sim.py --server http://localhost:8000 --scenario fall_demo --speed 2
    python simulator/sim.py --broker localhost --rooms 102,103,104

Transport : MQTT (paho) si `--broker` et joignable, sinon HTTP `POST /api/ingest` (lots d'1 s).
Écoute `hackcure/sim/scenario` (MQTT) pour lancer des scénarios à distance.

Intégrité des trames : si `EDGE_HMAC_KEY` est défini dans l'environnement (ou `--hmac-key`), chaque message porte
`seq` et `sig` (HMAC-SHA256, voir `docs/integrite-trames.md`) ; sinon rien n'est ajouté (mode démo du serveur).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simulator.engine import Scenario, SimEngine  # noqa: E402
from simulator.vitaldb_replay import VitalReplayer  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("hackcure.sim.cli")


class HttpTransport:
    def __init__(self, server: str, api_key: str = ""):
        import requests

        self.requests = requests
        self.url = server.rstrip("/") + "/api/ingest"
        self.headers = {"X-API-Key": api_key} if api_key else {}
        self.buffer: list[dict[str, Any]] = []
        self.last_flush = time.time()
        self.errors = 0

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        self.buffer.append({"topic": topic, "payload": payload})

    def flush(self) -> None:
        if not self.buffer:
            return
        batch, self.buffer = self.buffer, []
        try:
            r = self.requests.post(self.url, json={"messages": batch}, headers=self.headers, timeout=3)
            if r.status_code >= 400:
                logger.warning("Serveur: %s %s", r.status_code, r.text[:200])
            self.errors = 0
        except Exception as exc:
            self.errors += 1
            if self.errors in (1, 10, 100):
                logger.warning("Serveur injoignable (%s) — %d lots perdus", exc.__class__.__name__, self.errors)


class MqttTransport:
    def __init__(self, host: str, port: int, on_scenario):
        import paho.mqtt.client as mqtt

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2) if hasattr(mqtt, "CallbackAPIVersion") else mqtt.Client()
        self.on_scenario = on_scenario
        self.client.on_message = self._on_message
        self.client.connect(host, port, keepalive=30)
        self.client.subscribe("hackcure/sim/scenario")
        self.client.subscribe("hackcure/room/+/cmd/+")
        self.client.loop_start()
        self.on_cmd = None

    def _on_message(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode("utf-8"))
        except Exception:
            return
        if msg.topic == "hackcure/sim/scenario":
            self.on_scenario(data.get("name"), data.get("room"))
        elif self.on_cmd and "/cmd/" in msg.topic and not msg.topic.endswith("/cmd/ack"):
            parts = msg.topic.split("/")
            self.on_cmd(parts[2], parts[4], data.get("action"), data.get("value"), data.get("commandId"))

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        self.client.publish(topic, json.dumps(payload, default=str), qos=0)

    def flush(self) -> None:
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description="HackCure — simulateur de chambres et d'appareils")
    ap.add_argument("--server", default="http://localhost:8000", help="URL du serveur (repli HTTP)")
    ap.add_argument("--broker", default=None, help="Hôte MQTT (ex. localhost). Sans broker : HTTP.")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--rooms", default="101,102,103,104", help="Chambres simulées")
    ap.add_argument("--scenario", default=None, help="Scénario à lancer au démarrage")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--vitaldb", action="store_true", help="Tenter le rejeu VitalDB pour les profils (sinon synthétique)")
    ap.add_argument("--api-key", default="")
    ap.add_argument("--hmac-key", default=None, help="Clé de signature des trames (défaut : variable d'environnement EDGE_HMAC_KEY)")
    ap.add_argument("--list", action="store_true", help="Lister les scénarios")
    ap.add_argument("--duration", type=float, default=0, help="Arrêt après N secondes (0 = infini)")
    args = ap.parse_args()

    if args.list:
        for s in Scenario.available():
            print(f"{s['name']:<16} chambre {s['room']:<4} {s['description']}")
        return

    engine_holder: dict[str, SimEngine] = {}

    def on_scenario(name, room=None):
        eng = engine_holder.get("engine")
        if not eng or not name:
            return
        if name == "stop":
            eng.stop_scenario()
        try:
            eng.start_scenario(name, room)
        except FileNotFoundError as exc:
            logger.warning("%s", exc)

    transport: Any = None
    if args.broker:
        try:
            transport = MqttTransport(args.broker, args.port, on_scenario)
            logger.info("Transport MQTT %s:%s", args.broker, args.port)
        except Exception as exc:
            logger.warning("MQTT indisponible (%s) → HTTP %s", exc, args.server)
    if transport is None:
        transport = HttpTransport(args.server, args.api_key)
        logger.info("Transport HTTP %s", transport.url)

    rooms = [r.strip() for r in args.rooms.split(",") if r.strip()]
    engine = SimEngine(publish=transport.publish, rooms=rooms, speed=args.speed, hmac_key=args.hmac_key)
    logger.info("Intégrité des trames : %s", "signature HMAC-SHA256 active" if engine.signer is not None and engine.signer.enabled else "aucune clé (EDGE_HMAC_KEY), trames non signées")
    engine_holder["engine"] = engine
    if hasattr(transport, "on_cmd"):
        transport.on_cmd = engine.handle_command
    engine.on_scenario_event = lambda kind, data: logger.info("%s %s", kind, data)

    if args.vitaldb:
        rep = VitalReplayer(caseid=1, seconds=300, use_vitaldb=True)
        logger.info("Constantes de référence : %s", rep.source)
        if rep.source == "vitaldb":
            v = rep.next()
            for r in engine.rooms.values():
                r.profile.hr, r.profile.spo2, r.profile.sys, r.profile.dia = v["hr"], v["spo2"], v["sys"], v["dia"]

    if args.scenario:
        engine.start_scenario(args.scenario)

    logger.info("Simulation de %s (vitesse x%.1f). Ctrl+C pour arrêter.", ", ".join(rooms), args.speed)
    t0 = time.time()
    last_flush = time.time()
    try:
        while True:
            engine.tick()
            if time.time() - last_flush >= 1.0:
                transport.flush()
                last_flush = time.time()
            if args.duration and time.time() - t0 > args.duration:
                break
            time.sleep(0.25)
    except KeyboardInterrupt:
        pass
    finally:
        transport.flush()


if __name__ == "__main__":
    main()
