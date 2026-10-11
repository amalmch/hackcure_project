"""
Chiffrement au repos (V3, étape 3) : AES-256-GCM applicatif des champs sensibles de la base.

- Champs chiffrés : identité du patient (`Patient.first_name`, `Patient.last_name`), contenu des documents du dossier
  médical (`MedicalRecordEntry.content`), réponses aux questionnaires psychologiques (`PsychQuestionnaire.answers_json`).
- Clé : `DATA_ENCRYPTION_KEY` dans `.env` (32 octets en base64 url, générée par `scripts/make-key`). Jamais commitée.
- Format stocké : `enc:v1:` + base64(nonce de 12 octets + texte chiffré + étiquette d'authentification de 16 octets).
  Un nonce aléatoire par valeur ; l'étiquette GCM détecte toute modification en base.
- Transparence : le type de colonne `EncryptedStr` chiffre à l'écriture et déchiffre à la lecture ; le reste du code
  manipule du texte clair. Une valeur déjà en clair (base antérieure) est lue telle quelle, puis chiffrée par
  `migrate()` au démarrage.
- **Sans clé : la plateforme démarre et fonctionne en clair, avec un avertissement visible** (mode démo).
- Avec une base chiffrée mais sans la bonne clé : les champs s'affichent « 🔒 chiffré », rien n'est écrasé.

Limites assumées : la date de naissance (colonne de type date, utilisée pour calculer l'âge) et les champs de
recherche (titre, résumé) ne sont pas chiffrés ; pas de rotation de clé automatique ; la clé vit dans `.env`
(pas de coffre-fort matériel). Pour chiffrer toute la base, voir SQLCipher ou le chiffrement du disque.
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Any, Optional

from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

logger = logging.getLogger("hackcure.crypto")

PREFIX = "enc:v1:"
LOCKED = "🔒 chiffré"
AAD = b"hackcure-v1"
FIELDS = {"patient": ["first_name", "last_name"], "medicalrecordentry": ["content"], "psychquestionnaire": ["answers_json"]}
_warned: set[str] = set()


def _warn_once(key: str, message: str) -> None:
    if key not in _warned:
        _warned.add(key)
        logger.warning(message)


def generate_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")


def _key() -> Optional[bytes]:
    raw = os.getenv("DATA_ENCRYPTION_KEY", "").strip()
    if not raw:
        return None
    try:
        key = bytes.fromhex(raw) if len(raw) == 64 and all(c in "0123456789abcdefABCDEF" for c in raw) else base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except Exception:
        key = b""
    if len(key) != 32:
        _warn_once("badkey", "DATA_ENCRYPTION_KEY invalide (32 octets attendus, base64 url ou 64 caractères hexadécimaux) : chiffrement au repos DÉSACTIVÉ. Générer une clé : scripts/make-key")
        return None
    return key


def _aes(key: bytes) -> Any:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    return AESGCM(key)


def available() -> bool:
    try:
        import cryptography  # noqa: F401

        return True
    except Exception:
        return False


def enabled() -> bool:
    if _key() is None:
        return False
    if not available():
        _warn_once("nolib", "Bibliothèque « cryptography » absente : chiffrement au repos DÉSACTIVÉ (pip install cryptography)")
        return False
    return True


def encrypt(value: Optional[str]) -> Optional[str]:
    if value is None or value == "" or not isinstance(value, str) or value.startswith(PREFIX) or not enabled():
        return value
    nonce = os.urandom(12)
    return PREFIX + base64.b64encode(nonce + _aes(_key()).encrypt(nonce, value.encode("utf-8"), AAD)).decode("ascii")  # type: ignore[arg-type]


def decrypt(value: Optional[str]) -> Optional[str]:
    if not isinstance(value, str) or not value.startswith(PREFIX):
        return value  # valeur en clair (mode démo, ou base antérieure pas encore migrée)
    if not enabled():
        _warn_once("locked", "La base contient des champs chiffrés mais DATA_ENCRYPTION_KEY est absente ou invalide : ces champs restent illisibles (« 🔒 chiffré »).")
        return LOCKED
    try:
        blob = base64.b64decode(value[len(PREFIX):])
        return _aes(_key()).decrypt(blob[:12], blob[12:], AAD).decode("utf-8")  # type: ignore[arg-type]
    except Exception:  # mauvaise clé ou donnée altérée (étiquette GCM invalide)
        _warn_once("tag", "Déchiffrement impossible (mauvaise clé ou donnée modifiée en base) : champ affiché « 🔒 chiffré ».")
        return LOCKED


class EncryptedStr(TypeDecorator):
    """Colonne texte chiffrée de façon transparente (AES-256-GCM) quand `DATA_ENCRYPTION_KEY` est définie."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        return encrypt(value)

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        return decrypt(value)


def status() -> dict[str, Any]:
    on = enabled()
    return {"enabled": on, "algorithm": "AES-256-GCM", "fields": [f"{t}.{c}" for t, cols in FIELDS.items() for c in cols],
            "warning": None if on else "Chiffrement au repos inactif (DATA_ENCRYPTION_KEY absente) : données en clair, mode démo."}


def migrate(engine: Any) -> int:
    """Chiffre les valeurs encore en clair des champs sensibles (base créée avant l'activation de la clé). Idempotent."""
    if not enabled():
        return 0
    from sqlalchemy import inspect, text

    done = 0
    tables = set(inspect(engine).get_table_names())
    with engine.begin() as conn:
        for table, cols in FIELDS.items():
            if table not in tables:
                continue
            for col in cols:
                rows = conn.execute(text(f"SELECT id, {col} FROM {table} WHERE {col} IS NOT NULL AND {col} != '' AND {col} NOT LIKE :p"), {"p": PREFIX + "%"}).fetchall()
                for rid, value in rows:
                    conn.execute(text(f"UPDATE {table} SET {col} = :v WHERE id = :i"), {"v": encrypt(value), "i": rid})
                    done += 1
    if done:
        logger.info("Chiffrement au repos : %d valeur(s) en clair chiffrée(s) (AES-256-GCM)", done)
    return done
