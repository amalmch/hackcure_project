"""
Intégrité des trames IoT côté serveur (V3, étape 5) : `check(topic, payload, via)` est appelé par
`handler.handle()` juste après la validation du contrat, quel que soit le canal (MQTT, HTTP, simulateur embarqué).

Avec une clé (`EDGE_HMAC_KEY` non vide) — mode `enforced` — une trame est rejetée si :
- `sig` ou `seq` est absent ou mal formé                              → `unsigned` ;
- la signature HMAC-SHA256 ne correspond pas                          → `bad_signature` ;
- `ts` a plus de `FRAME_MAX_AGE_S` secondes (30 par défaut), ou est en avance de plus de `FRAME_MAX_FUTURE_S` (5) → `stale` ;
- `seq` n'est pas supérieur à la dernière séquence acceptée de l'émetteur (`source` + chambre) → `replay`.
  Redémarrage d'un émetteur : une séquence plus basse est acceptée seulement si la trame est fraîche (contrôle précédent)
  ET si rien n'a été accepté de cet émetteur depuis plus de `FRAME_MAX_AGE_S` secondes. Une trame rejouée après ce silence
  est forcément trop ancienne, donc déjà rejetée par le contrôle `stale`. (Les émetteurs du projet démarrent en plus leur
  compteur à l'heure courante en millisecondes : un redémarrage rapide repart au-dessus de l'ancienne séquence.)

Sans clé — mode `demo` — tout est accepté et compté `unverified`, avec un avertissement dans les journaux et dans l'interface.

Exemptés (émis par le serveur lui-même) : les commandes `…/cmd/{équipement}` (pas `…/cmd/ack`), `hackcure/sim/scenario`,
et les messages internes `via="virtual"` (acquittement de l'edge virtuel du serveur).
"""

from __future__ import annotations

import importlib.util
import logging
import os
import re
import sys
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from ..config import PROJECT_ROOT

logger = logging.getLogger("hackcure.integrity")


def _load_primitives():
    """Primitives partagées (`contracts/integrity.py`), importées par chemin si le paquet `contracts` n'est pas importable."""
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from contracts import integrity as mod  # type: ignore

        if hasattr(mod, "verify") and hasattr(mod, "Signer"):
            return mod
    except Exception:
        pass
    spec = importlib.util.spec_from_file_location("hackcure_contracts_integrity", PROJECT_ROOT / "contracts" / "integrity.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


primitives = _load_primitives()

REASONS = ("bad_signature", "replay", "stale", "unsigned")
REASON_LABELS = {"bad_signature": "signature invalide", "replay": "rejeu (séquence déjà vue)", "stale": "trame trop ancienne ou horodatage invalide", "unsigned": "trame non signée"}
EXEMPT_VIA = ("virtual",)
RECENT_LEN = 20
DEMO_WARNING = "Mode démo — clé EDGE_HMAC_KEY non configurée, trames acceptées sans vérification"

_ROOM_RE = re.compile(r"/room/([^/]+)/")
_CMD_RE = re.compile(r"/cmd/([^/]+)$")


# ── configuration (accesseurs : les tests les remplacent ou changent l'environnement) ──
def get_key() -> str:
    return (os.getenv("EDGE_HMAC_KEY") or "").strip()


def max_age_s() -> float:
    try:
        return float(os.getenv("FRAME_MAX_AGE_S", "30"))
    except ValueError:
        return 30.0


def max_future_s() -> float:
    try:
        return float(os.getenv("FRAME_MAX_FUTURE_S", "5"))
    except ValueError:
        return 5.0


def mode() -> str:
    return "enforced" if get_key() else "demo"


def _now() -> float:
    return time.time()


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


# ── état en mémoire ───────────────────────────────────────────────────────────
@dataclass
class Verdict:
    ok: bool
    status: str  # verified | unverified | exempt | rejected
    reason: Optional[str] = None  # bad_signature | replay | stale | unsigned
    sender: str = ""
    seq: Optional[int] = None
    mode: str = "demo"


class FrameRejected(Exception):
    """Trame refusée par le contrôle d'intégrité (HTTP : 401 ; MQTT et simulateur embarqué : journalisée puis ignorée)."""

    def __init__(self, verdict: Verdict, topic: str = ""):
        self.verdict = verdict
        self.reason = verdict.reason or "rejected"
        self.topic = topic
        super().__init__(f"trame rejetée ({REASON_LABELS.get(self.reason, self.reason)})")


counters: dict[str, int] = {}
senders: dict[str, dict[str, Any]] = {}  # émetteur -> {last_seq, last_accepted (epoch), accepted}
recent: deque = deque(maxlen=RECENT_LEN)  # rejets les plus récents (le dernier en fin de file)
_flags = {"demo_warned": False}
_last_log: dict[str, float] = {}


def reset() -> None:
    """Remet tout à zéro (compteurs, séquences, rejets). Utilisé par les tests."""
    counters.clear()
    counters.update({"verified": 0, "unverified": 0, "exempt": 0, "rejected": 0, **{r: 0 for r in REASONS}})
    senders.clear()
    recent.clear()
    _last_log.clear()
    _flags["demo_warned"] = False


reset()


def sender_id(topic: str, payload: dict[str, Any]) -> str:
    m = _ROOM_RE.search(topic)
    return f"{payload.get('source', '?')}@{m.group(1) if m else '-'}"


def is_exempt(topic: str, via: str) -> bool:
    if via in EXEMPT_VIA or topic.endswith("/sim/scenario"):
        return True
    m = _CMD_RE.search(topic)
    return bool(m and m.group(1) != "ack")


def _reject(reason: str, topic: str, sender: str, seq: Any, via: str) -> Verdict:
    now = _now()
    counters["rejected"] += 1
    counters[reason] += 1
    recent.append({"reason": reason, "label": REASON_LABELS[reason], "topic": topic, "sender": sender, "seq": seq if isinstance(seq, int) else None, "via": via, "at": _iso(now)})
    if now - _last_log.get(reason, 0.0) >= 5.0:  # pas d'inondation des journaux en cas d'attaque ou de mauvaise clé
        _last_log[reason] = now
        logger.warning("Trame rejetée (%s) : %s de %s via %s — %d rejet(s) au total", REASON_LABELS[reason], topic, sender, via, counters["rejected"])
    return Verdict(False, "rejected", reason, sender, seq if isinstance(seq, int) else None, "enforced")


def check(topic: str, payload: dict[str, Any], via: str = "http") -> Verdict:
    """Contrôle une trame entrante et met à jour les compteurs. Ne lève jamais d'exception."""
    key = get_key()
    if is_exempt(topic, via):
        counters["exempt"] += 1
        return Verdict(True, "exempt", mode="enforced" if key else "demo")
    sender = sender_id(topic, payload)
    if not key:
        counters["unverified"] += 1
        if not _flags["demo_warned"]:
            _flags["demo_warned"] = True
            logger.warning("Intégrité des trames : %s", DEMO_WARNING)
        return Verdict(True, "unverified", sender=sender, mode="demo")
    _flags["demo_warned"] = False

    seq, sig = payload.get("seq"), payload.get("sig")
    if not isinstance(sig, str) or not sig or not isinstance(seq, int) or isinstance(seq, bool):
        return _reject("unsigned", topic, sender, seq, via)
    if not primitives.verify(topic, payload, key):
        return _reject("bad_signature", topic, sender, seq, via)
    now = _now()
    ts = primitives.parse_ts(payload.get("ts"))
    limit = max_age_s()
    if ts is None or now - ts > limit or ts - now > max_future_s():
        return _reject("stale", topic, sender, seq, via)
    st = senders.get(sender)
    if st is not None and seq <= st["last_seq"]:
        if now - st["last_accepted"] <= limit:
            return _reject("replay", topic, sender, seq, via)
        logger.info("Intégrité des trames : %s repart d'une séquence plus basse après %.0f s de silence (redémarrage)", sender, now - st["last_accepted"])
    if st is None:
        st = senders[sender] = {"last_seq": seq, "last_accepted": now, "accepted": 0}
    st["last_seq"], st["last_accepted"] = seq, now
    st["accepted"] += 1
    counters["verified"] += 1
    return Verdict(True, "verified", sender=sender, seq=seq, mode="enforced")


def snapshot() -> dict[str, Any]:
    """État exposé par `GET /api/integrity`."""
    enforced = bool(get_key())
    rejections = list(recent)[::-1]  # le plus récent d'abord
    return {
        "mode": "enforced" if enforced else "demo",
        "keyConfigured": enforced,
        "algorithm": primitives.ALGORITHM,
        "maxAgeS": max_age_s(),
        "maxFutureS": max_future_s(),
        "warning": None if enforced else DEMO_WARNING,
        "counters": {
            "accepted": counters["verified"] + counters["unverified"],
            "verified": counters["verified"],
            "unverified": counters["unverified"],
            "exempt": counters["exempt"],
            "rejected": counters["rejected"],
            "byReason": {r: counters[r] for r in REASONS},
        },
        "senders": [{"sender": s, "lastSeq": v["last_seq"], "accepted": v["accepted"], "lastAcceptedAt": _iso(v["last_accepted"])} for s, v in sorted(senders.items())],
        "lastRejection": rejections[0] if rejections else None,
        "recentRejections": rejections,
    }
