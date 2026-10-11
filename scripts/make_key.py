"""
Clés de sécurité de la plateforme (V3).

    python scripts/make_key.py                 # affiche une clé AES-256 (DATA_ENCRYPTION_KEY) et une clé HMAC (EDGE_HMAC_KEY)
    python scripts/make_key.py --write         # les écrit dans .env si elles n'y sont pas déjà (ne remplace jamais une clé existante)

ATTENTION : une base chiffrée n'est lisible qu'avec SA clé. Sauvegarder DATA_ENCRYPTION_KEY hors du serveur ;
la perdre, c'est perdre les champs chiffrés. Ne jamais commiter .env.
"""

from __future__ import annotations

import argparse
import base64
import os
import secrets
import sys
from pathlib import Path

ENV = Path(__file__).resolve().parents[1] / ".env"


def new_keys() -> dict[str, str]:
    return {"DATA_ENCRYPTION_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode("ascii"), "EDGE_HMAC_KEY": secrets.token_hex(32)}


def write_env(path: Path, keys: dict[str, str]) -> list[str]:
    """Ajoute les clés absentes ou vides ; renvoie les noms réellement écrits."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    written = []
    for name, value in keys.items():
        idx = next((i for i, l in enumerate(lines) if l.strip().startswith(name + "=")), None)
        if idx is not None and lines[idx].split("=", 1)[1].strip():
            continue  # déjà définie : on ne remplace jamais une clé existante
        if idx is None:
            lines.append(f"{name}={value}")
        else:
            lines[idx] = f"{name}={value}"
        written.append(name)
    if written:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description="Génère DATA_ENCRYPTION_KEY (AES-256-GCM) et EDGE_HMAC_KEY (HMAC-SHA256)")
    ap.add_argument("--write", action="store_true", help="écrire dans .env les clés absentes")
    ap.add_argument("--env", default=str(ENV))
    a = ap.parse_args()
    keys = new_keys()
    if a.write:
        done = write_env(Path(a.env), keys)
        print(("Clés écrites dans " + a.env + " : " + ", ".join(done)) if done else "Les clés existent déjà dans .env : rien n'a été modifié.")
        if "DATA_ENCRYPTION_KEY" in done:
            print("Sauvegarder DATA_ENCRYPTION_KEY hors du serveur. Au prochain démarrage, les champs sensibles encore en clair seront chiffrés.")
        if "EDGE_HMAC_KEY" in done:
            print("Copier EDGE_HMAC_KEY sur le Raspberry Pi (variable d'environnement ou edge/config/room101.yaml).")
    else:
        for k, v in keys.items():
            print(f"{k}={v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
