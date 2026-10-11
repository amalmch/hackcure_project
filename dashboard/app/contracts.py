"""
Chargement et validation des contrats JSON Schema (`contracts/schemas/*.json`).
Partagé par l'ingestion HTTP/MQTT, le simulateur embarqué et les tests.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from .config import CONTRACTS_DIR

SCHEMAS_DIR = CONTRACTS_DIR / "schemas"

# Ordre important : `cmd/ack` doit précéder `cmd/{equipment}`
_TOPIC_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^hackcure/room/(?P<room>\d{3})/vision/state$"), "vision_state"),
    (re.compile(r"^hackcure/room/(?P<room>\d{3})/vision/staff$"), "vision_staff"),
    (re.compile(r"^hackcure/room/(?P<room>\d{3})/vision/expression$"), "vision_expression"),
    (re.compile(r"^hackcure/room/(?P<room>\d{3})/vision/behavior$"), "vision_behavior"),
    (re.compile(r"^hackcure/room/(?P<room>\d{3})/thermal$"), "thermal"),
    (re.compile(r"^hackcure/room/(?P<room>\d{3})/env$"), "env"),
    (re.compile(r"^hackcure/room/(?P<room>\d{3})/call$"), "call"),
    (re.compile(r"^hackcure/room/(?P<room>\d{3})/device/(?P<device>[A-Za-z0-9_\-]+)$"), "device"),
    (re.compile(r"^hackcure/room/(?P<room>\d{3})/safety/alarm$"), "safety_alarm"),
    (re.compile(r"^hackcure/room/(?P<room>\d{3})/cmd/ack$"), "cmd_ack"),
    (re.compile(r"^hackcure/room/(?P<room>\d{3})/cmd/(?P<equipment>[a-z_]+)$"), "cmd"),
    (re.compile(r"^hackcure/sim/scenario$"), "sim_scenario"),
]


class ContractError(ValueError):
    pass


@lru_cache(maxsize=None)
def load_schema(name: str) -> dict[str, Any]:
    path = SCHEMAS_DIR / f"{name}.json"
    if not path.exists():
        raise ContractError(f"Schéma inconnu : {name}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def all_schema_names() -> list[str]:
    return sorted(p.stem for p in SCHEMAS_DIR.glob("*.json") if not p.stem.startswith("_"))


def parse_topic(topic: str) -> tuple[str, dict[str, str]] | None:
    """Retourne (nom_du_schéma, groupes {room, device, equipment}) ou None."""
    for rx, name in _TOPIC_RULES:
        m = rx.match(topic)
        if m:
            return name, {k: v for k, v in m.groupdict().items() if v is not None}
    return None


def schema_for_topic(topic: str) -> dict[str, Any] | None:
    parsed = parse_topic(topic)
    return load_schema(parsed[0]) if parsed else None


@lru_cache(maxsize=None)
def _validator(name: str):
    from jsonschema import Draft202012Validator

    return Draft202012Validator(load_schema(name))


def validate(topic: str, payload: dict[str, Any]) -> tuple[str, dict[str, str]]:
    """Valide `payload` contre le schéma du topic. Lève ContractError sinon."""
    parsed = parse_topic(topic)
    if parsed is None:
        raise ContractError(f"Topic non reconnu : {topic}")
    name, groups = parsed
    errors = sorted(_validator(name).iter_errors(payload), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        loc = "/".join(str(p) for p in first.path) or "<racine>"
        raise ContractError(f"{name}: {loc}: {first.message}")
    return name, groups


def is_valid(topic: str, payload: dict[str, Any]) -> bool:
    try:
        validate(topic, payload)
        return True
    except ContractError:
        return False
