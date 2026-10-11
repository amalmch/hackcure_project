"""
Intégrité des trames IoT : numéro de séquence, horodatage et signature HMAC-SHA256.

Module **sans dépendance** (bibliothèque standard uniquement), partagé par le serveur
(`dashboard/app/ingest/integrity.py`), l'edge (`edge/transport`), le simulateur (`simulator/engine.py`)
et `dashboard/camera_loop.py`. Il ne doit jamais importer le paquet du serveur.

Format (champs ajoutés DANS le payload de chaque message) :
- `seq` : entier strictement croissant par émetteur (émetteur = `source` + chambre) ;
- `ts`  : horodatage ISO 8601 UTC déjà présent sur tous les messages, c'est l'horodatage signé ;
- `sig` : HMAC-SHA256 en hexadécimal minuscule, calculé avec la clé partagée `EDGE_HMAC_KEY` sur les octets UTF-8 de
          `topic + "\\n" + canonical(payload sans "sig")`.

Sans clé (`EDGE_HMAC_KEY` vide) les émetteurs n'ajoutent rien : c'est le mode démo, le serveur accepte tout avec un avertissement.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

ENV_KEY = "EDGE_HMAC_KEY"
ALGORITHM = "HMAC-SHA256"


def env_key() -> str:
    """Clé partagée lue dans l'environnement (chaîne vide = pas de signature)."""
    return (os.getenv(ENV_KEY) or "").strip()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical(obj: Any) -> str:
    """JSON canonique : clés triées, sans espaces, UTF-8 non échappé (identique côté émetteur et côté serveur)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def signature(topic: str, payload: dict[str, Any], key: str) -> str:
    """Signature hexadécimale de `payload` (le champ `sig` éventuel est ignoré)."""
    body = {k: v for k, v in payload.items() if k != "sig"}
    data = (topic + "\n" + canonical(body)).encode("utf-8")
    return hmac.new(key.encode("utf-8"), data, hashlib.sha256).hexdigest()


def sign(topic: str, payload: dict[str, Any], key: str, seq: int) -> dict[str, Any]:
    """Renvoie une COPIE du payload avec `seq` et `sig` (le payload d'origine n'est pas modifié)."""
    out = {k: v for k, v in payload.items() if k != "sig"}
    out["seq"] = int(seq)
    out["sig"] = signature(topic, out, key)
    return out


def verify(topic: str, payload: dict[str, Any], key: str) -> bool:
    """Vrai si `payload["sig"]` est la signature attendue (comparaison en temps constant)."""
    sig = payload.get("sig")
    if not isinstance(sig, str) or not sig or not key:
        return False
    try:
        return hmac.compare_digest(signature(topic, payload, key), sig.strip().lower())
    except Exception:
        return False


def parse_ts(value: Any) -> Optional[float]:
    """Horodatage ISO 8601 → secondes epoch (None si illisible). Sans fuseau : considéré UTC."""
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


class Signer:
    """Signe les messages sortants d'un émetteur (compteur de séquence protégé par un verrou).

    - `key=None` : la clé est relue dans l'environnement (`EDGE_HMAC_KEY`) à chaque message ; sans clé, `sign()` renvoie le payload tel quel.
    - Le compteur démarre à l'heure courante en millisecondes : un émetteur redémarré repart donc toujours AU-DESSUS
      de sa séquence précédente (pas de trou de 30 s après un redémarrage rapide).
    """

    def __init__(self, key: Optional[str] = None, start: Optional[int] = None):
        self._key = key
        self._seq = int(start) if start is not None else int(time.time() * 1000)
        self.lock = threading.RLock()

    @property
    def key(self) -> str:
        return (self._key or "").strip() if self._key is not None else env_key()

    @property
    def enabled(self) -> bool:
        return bool(self.key)

    def next_seq(self) -> int:
        with self.lock:
            self._seq += 1
            return self._seq

    def sign(self, topic: str, payload: dict[str, Any], restamp: bool = False) -> dict[str, Any]:
        """Payload signé (copie) ou payload inchangé s'il n'y a pas de clé.

        `restamp=True` (trame renvoyée après une coupure) : `ts` devient l'heure d'envoi, l'heure de mesure
        d'origine est conservée dans `measuredAt`, et la trame reçoit une séquence fraîche.
        """
        key = self.key
        if not key:
            return payload
        out = {k: v for k, v in payload.items() if k not in ("sig", "seq")}
        if restamp:
            out.setdefault("measuredAt", out.get("ts"))
            out["ts"] = now_iso()
        with self.lock:
            return sign(topic, out, key, self.next_seq())
