"""
Lanceur de la plateforme : écoute en IPv4 **et** en IPv6.

    python serve.py [--port 8000] [--host 0.0.0.0]

Pourquoi : sous Windows, `localhost` est d'abord résolu en IPv6 (`::1`). Avec `uvicorn --host 0.0.0.0` (IPv4 seul),
chaque nouvelle connexion du navigateur à http://localhost:8000 attend ~3 s l'échec en IPv6 avant de retomber
sur 127.0.0.1 : l'interface semble figée par à-coups. n8n (Node) échouait pour la même raison.
`uvicorn server:app` reste utilisable tel quel (point d'entrée conservé).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import socket
import ssl
import sys
from pathlib import Path
from typing import Optional

import uvicorn

DASHBOARD_DIR = Path(__file__).resolve().parent


def listening_sockets(host: str, port: int) -> list[socket.socket]:
    socks: list[socket.socket] = []
    s4 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s4.bind((host, port))
    socks.append(s4)
    if host in ("0.0.0.0", "127.0.0.1"):
        try:
            s6 = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            s6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            s6.bind(("::" if host == "0.0.0.0" else "::1", port))
            socks.append(s6)
        except OSError:  # IPv6 désactivé sur la machine : IPv4 seul
            pass
    return socks


def _truthy(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def _load_env() -> None:
    """`.env` de la racine (le serveur le relit ensuite lui-même) : le lanceur a besoin de HTTPS et des chemins du certificat."""
    try:
        from dotenv import load_dotenv

        load_dotenv(DASHBOARD_DIR.parent / ".env")
    except Exception:
        pass


def tls_files() -> Optional[tuple[Path, Path]]:
    """Certificat et clé pour HTTPS=true. Les crée (auto-signés) s'ils manquent ; None si c'est impossible."""
    base = Path(os.getenv("TLS_CERT_DIR") or DASHBOARD_DIR / "certs")
    crt = Path(os.getenv("TLS_CERT_FILE") or base / "server.crt")
    key = Path(os.getenv("TLS_KEY_FILE") or base / "server.key")
    for path in (crt, key):
        if not path.is_absolute() and not path.exists() and (DASHBOARD_DIR.parent / path).exists():
            crt, key = DASHBOARD_DIR.parent / crt, DASHBOARD_DIR.parent / key
            break
    if crt.exists() and key.exists():
        return crt, key
    try:
        sys.path.insert(0, str(DASHBOARD_DIR.parent / "scripts"))
        from make_cert import make_cert

        return make_cert(crt.parent)
    except Exception as exc:
        print(f"AVERTISSEMENT : HTTPS=true mais aucun certificat utilisable ({exc.__class__.__name__}: {exc}). Générer : scripts/make-cert", flush=True)
        return None


def tls13_context(crt: Path, key: Path) -> ssl.SSLContext:
    """Contexte serveur : TLS 1.3 minimum (les versions antérieures sont refusées à la poignée de main)."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.load_cert_chain(str(crt), str(key))
    return ctx


def main() -> None:
    ap = argparse.ArgumentParser(description="Hospital Copilot — serveur (IPv4 + IPv6)")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()
    _load_env()
    socks = listening_sockets(args.host, args.port)
    files = tls_files() if _truthy(os.getenv("HTTPS")) else None
    scheme = "http"
    if files:
        config = uvicorn.Config("server:app", log_level="info", ssl_certfile=str(files[0]), ssl_keyfile=str(files[1]))
        config.load()
        config.ssl = tls13_context(*files)  # V3 : TLS 1.3 minimum
        os.environ["HACKCURE_TLS_ACTIVE"] = "1"  # lu par /health (security.https)
        scheme = "https"
    else:
        if _truthy(os.getenv("HTTPS")):
            print("AVERTISSEMENT : démarrage en HTTP (clair) malgré HTTPS=true.", flush=True)
        config = uvicorn.Config("server:app", log_level="info")
    server = uvicorn.Server(config)
    print(f"Hospital Copilot : {scheme}://localhost:{args.port}  ({' + '.join('IPv6' if s.family == socket.AF_INET6 else 'IPv4' for s in socks)})" + ("  [TLS 1.3, certificat auto-signé]" if files else ""), flush=True)
    asyncio.run(server.serve(sockets=socks))


if __name__ == "__main__":
    main()
