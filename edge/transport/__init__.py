"""
Transport edge → serveur : MQTT (paho) si le broker répond, sinon repli HTTP `POST /api/ingest` (lots),
avec **file locale hors ligne** (jsonl) renvoyée à la reconnexion. Réception des commandes :
abonnement MQTT `hackcure/room/{room}/cmd/+`, ou long-poll HTTP `GET /api/edge/commands`.

Intégrité des trames (V3) : si une clé est configurée (`EDGE_HMAC_KEY` dans l'environnement, sinon `security.hmac_key`
du YAML), chaque payload est signé AU MOMENT OÙ IL PART (`seq` croissant + `sig` HMAC-SHA256, voir `contracts/integrity.py`
et `docs/integrite-trames.md`). Sans clé, rien n'est ajouté. Les messages de la file hors ligne sont ré-horodatés à
l'envoi (`ts` = heure d'envoi, heure de mesure conservée dans `measuredAt`, séquence fraîche) : sinon le serveur les
rejetterait comme trop anciens (> 30 s).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger("edge.transport")

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
try:
    from contracts.integrity import Signer  # noqa: E402  (bibliothèque standard uniquement)
except Exception:  # dossier `contracts/` non déployé sur le Pi : pas de signature
    Signer = None  # type: ignore


def build_signer(hmac_key: Optional[str] = None):
    """Signataire des trames sortantes. `hmac_key=None` : clé lue dans EDGE_HMAC_KEY ; sans clé, les payloads partent inchangés."""
    if Signer is None:
        if hmac_key or os.getenv("EDGE_HMAC_KEY"):
            logger.warning("Clé HMAC configurée mais `contracts/integrity.py` introuvable : trames NON signées")
        return None
    return Signer(hmac_key or None)
CommandHandler = Callable[[str, str, Any, str, Optional[str]], tuple[bool, str, Optional[str]]]


class OfflineQueue:
    def __init__(self, path: Optional[str], max_items: int = 5000):
        self.path = Path(path) if path else None
        self.items: list[dict[str, Any]] = []
        self.max_items = max_items
        if self.path and self.path.exists():
            try:
                self.items = [json.loads(l) for l in self.path.read_text(encoding="utf-8").splitlines() if l.strip()]
            except Exception:
                self.items = []

    def push(self, topic: str, payload: dict[str, Any]) -> None:
        self.items.append({"topic": topic, "payload": payload})
        if len(self.items) > self.max_items:
            self.items = self.items[-self.max_items:]
        self._save()

    def drain(self) -> list[dict[str, Any]]:
        items, self.items = self.items, []
        self._save()
        return items

    def __len__(self) -> int:
        return len(self.items)

    def _save(self) -> None:
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("\n".join(json.dumps(i, ensure_ascii=False) for i in self.items), encoding="utf-8")
        except Exception:
            logger.debug("file hors ligne non sauvegardée", exc_info=True)


class HttpTransport:
    def __init__(self, server_url: str, room: str, api_key: str = "", queue_file: Optional[str] = None, flush_every_s: float = 1.0, hmac_key: Optional[str] = None):
        import requests

        self.signer = build_signer(hmac_key)
        self._send_lock = threading.RLock()  # un seul envoi à la fois : les séquences arrivent dans l'ordre

        self.requests = requests
        self.base = server_url.rstrip("/")
        self.room = room
        self.headers = {"X-API-Key": api_key} if api_key else {}
        self.buffer: list[dict[str, Any]] = []
        self.queue = OfflineQueue(queue_file)
        self.flush_every = flush_every_s
        self.last_flush = 0.0
        self.online = False
        self.errors = 0
        self.command_handler: Optional[CommandHandler] = None
        self._poll_thread: Optional[threading.Thread] = None
        self._stop = False

    def publish(self, topic: str, payload: dict[str, Any], critical: bool = False) -> None:
        self.buffer.append({"topic": topic, "payload": payload})
        if critical:
            self.flush(force=True)

    def _signed(self, messages: list[dict[str, Any]], restamp: bool = False) -> list[dict[str, Any]]:
        """Copie signée des messages, juste avant l'envoi (les originaux, non signés, restent ceux mis en file)."""
        if self.signer is None or not self.signer.enabled:
            return messages
        return [{"topic": m["topic"], "payload": self.signer.sign(m["topic"], m["payload"], restamp=restamp)} for m in messages]

    def flush(self, force: bool = False) -> bool:
        with self._send_lock:
            return self._flush(force)

    def _flush(self, force: bool = False) -> bool:
        now = time.time()
        if not force and now - self.last_flush < self.flush_every:
            return self.online
        self.last_flush = now
        queued = self.queue.drain() if self.online or not self.queue.items else []
        batch = queued + self.buffer
        if not batch and not self.queue.items:
            return self.online
        self.buffer = []
        try:
            # file hors ligne d'abord (ré-horodatée), puis les messages courants : séquences croissantes dans le lot
            wire = self._signed(queued, restamp=True) + self._signed(batch[len(queued):])
            r = self.requests.post(f"{self.base}/api/ingest", json={"messages": wire}, headers=self.headers, timeout=3)
            if r.status_code >= 500:
                raise RuntimeError(f"HTTP {r.status_code}")
            if not self.online:
                logger.info("Serveur joignable : %d message(s) renvoyé(s)", len(batch))
            self.online = True
            self.errors = 0
            if self.queue.items:  # ce qui restait en file
                rest = self.queue.drain()
                if rest:
                    self.requests.post(f"{self.base}/api/ingest", json={"messages": self._signed(rest, restamp=True)}, headers=self.headers, timeout=3)
            return True
        except Exception as exc:
            self.errors += 1
            if self.online or self.errors in (1, 20, 200):
                logger.warning("Serveur injoignable (%s) : %d message(s) en file hors ligne", exc.__class__.__name__, len(batch))
            self.online = False
            for m in batch:
                if "/safety/alarm" in m["topic"] or "/vision/staff" in m["topic"] or "/call" in m["topic"]:
                    self.queue.push(m["topic"], m["payload"])  # on ne garde hors ligne que les messages importants
            return False

    def start_command_polling(self, handler: CommandHandler, ack_publish: Callable[[str, dict[str, Any]], None]) -> None:
        self.command_handler = handler

        def loop():
            while not self._stop:
                try:
                    r = self.requests.get(f"{self.base}/api/edge/commands", params={"room": self.room}, headers=self.headers, timeout=5)
                    if r.ok:
                        for c in r.json().get("commands", []):
                            ok, state, err = handler(c["equipment"], c["action"], c.get("value"), c.get("requestedBy", "server"), c.get("commandId"))
                            ack_publish(c["equipment"], c["action"], ok, state, c.get("commandId"), err)
                except Exception:
                    time.sleep(3)
                time.sleep(1.0)

        self._poll_thread = threading.Thread(target=loop, daemon=True)
        self._poll_thread.start()

    def stop(self) -> None:
        self._stop = True
        self.flush(force=True)


class MqttTransport:
    def __init__(self, host: str, port: int, room: str, prefix: str = "hackcure", hmac_key: Optional[str] = None, tls: bool = False, ca_file: Optional[str] = None):
        import paho.mqtt.client as mqtt

        self.signer = build_signer(hmac_key)
        self.room, self.prefix = room, prefix
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2) if hasattr(mqtt, "CallbackAPIVersion") else mqtt.Client()
        self.client.on_message = self._on_message
        self.client.on_connect = lambda *a, **k: logger.info("MQTT connecté %s:%s%s", host, port, " (TLS)" if tls else "")
        if tls:  # V3 : chiffrement en transit entre le Pi et le broker (port 8883) ; ca_file = autorité qui a signé le certificat du broker
            import ssl

            self.client.tls_set(ca_certs=ca_file or None, tls_version=ssl.PROTOCOL_TLS_CLIENT)
        self.client.connect(host, port, keepalive=30)
        self.client.subscribe(f"{prefix}/room/{room}/cmd/+")
        self.client.loop_start()
        self.command_handler: Optional[CommandHandler] = None
        self.ack_publish: Optional[Callable] = None
        self.online = True

    def _on_message(self, client, userdata, msg):
        if msg.topic.endswith("/cmd/ack") or not self.command_handler:
            return
        try:
            data = json.loads(msg.payload.decode("utf-8"))
        except Exception:
            return
        equipment = msg.topic.split("/")[-1]
        ok, state, err = self.command_handler(equipment, data.get("action", ""), data.get("value"), data.get("requestedBy", "server"), data.get("commandId"))
        if self.ack_publish:
            self.ack_publish(equipment, data.get("action", ""), ok, state, data.get("commandId"), err)

    def publish(self, topic: str, payload: dict[str, Any], critical: bool = False) -> None:
        if self.signer is not None and self.signer.enabled:
            with self.signer.lock:  # signature et remise au client MQTT dans le même verrou : ordre des séquences garanti
                self.client.publish(topic, json.dumps(self.signer.sign(topic, payload), default=str), qos=1 if critical else 0)
            return
        self.client.publish(topic, json.dumps(payload, default=str), qos=1 if critical else 0)

    def flush(self, force: bool = False) -> bool:
        return self.client.is_connected()

    def start_command_polling(self, handler: CommandHandler, ack_publish) -> None:
        self.command_handler, self.ack_publish = handler, ack_publish

    def stop(self) -> None:
        self.client.loop_stop()


def build_transport(cfg: dict[str, Any], room: str, broker: Optional[str] = None, server: Optional[str] = None):
    """MQTT si un hôte est configuré et répond, sinon HTTP (repli)."""
    mq = cfg.get("mqtt", {}) or {}
    host = broker or mq.get("host")
    # clé de signature des trames : variable d'environnement EDGE_HMAC_KEY en priorité, sinon `security.hmac_key` du YAML
    hmac_key = (os.getenv("EDGE_HMAC_KEY") or str((cfg.get("security", {}) or {}).get("hmac_key") or "")).strip()
    logger.info("Intégrité des trames : %s", "signature HMAC-SHA256 active" if hmac_key else "aucune clé (EDGE_HMAC_KEY), trames non signées")
    if host:
        try:
            tls = bool(mq.get("tls")) or os.getenv("MQTT_TLS", "").strip().lower() in ("1", "true", "yes", "on")
            t = MqttTransport(host, int(mq.get("port", 8883 if tls else 1883)), room, mq.get("prefix", "hackcure"), hmac_key=hmac_key, tls=tls, ca_file=mq.get("ca_file") or os.getenv("MQTT_CA_FILE") or None)
            return t, "mqtt"
        except Exception as exc:
            logger.warning("Broker MQTT %s injoignable (%s) → repli HTTP", host, exc.__class__.__name__)
    srv = cfg.get("server", {}) or {}
    url = server or srv.get("url", "http://localhost:8000")
    return HttpTransport(url, room, srv.get("api_key", ""), cfg.get("rules", {}).get("offline_queue_file"), hmac_key=hmac_key), "http"
