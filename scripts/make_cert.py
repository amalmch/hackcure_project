"""
Certificat TLS auto-signé de démonstration (V3, étape 3).

    python scripts/make_cert.py                      # écrit dashboard/certs/server.crt et server.key (valables 1 an)
    python scripts/make_cert.py --dir /data/certs --host clinique.local --host 192.168.1.20

Le certificat couvre localhost, 127.0.0.1, ::1, le nom de la machine et les noms / adresses passés par --host.
Auto-signé : le navigateur affiche un avertissement à accepter une fois. En production : certificat d'une autorité
reconnue (ou tunnel Cloudflare, voir docs/securite.md). La clé privée n'est jamais commitée (*.key est ignoré par git).
"""

from __future__ import annotations

import argparse
import ipaddress
import socket
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_DIR = Path(__file__).resolve().parents[1] / "dashboard" / "certs"


def make_cert(directory: Path = DEFAULT_DIR, hosts: list[str] | None = None, days: int = 365, force: bool = False) -> tuple[Path, Path]:
    """Génère (ou réutilise) server.crt / server.key. Renvoie leurs chemins."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    directory = Path(directory)
    crt, key = directory / "server.crt", directory / "server.key"
    if crt.exists() and key.exists() and not force:
        return crt, key
    directory.mkdir(parents=True, exist_ok=True)
    private = ec.generate_private_key(ec.SECP256R1())
    names: list[x509.GeneralName] = []
    for h in dict.fromkeys(["localhost", "127.0.0.1", "::1", socket.gethostname(), *(hosts or [])]):
        try:
            names.append(x509.IPAddress(ipaddress.ip_address(h)))
        except ValueError:
            if h:
                names.append(x509.DNSName(h))
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Hospital Copilot (demo)"), x509.NameAttribute(NameOID.ORGANIZATION_NAME, "HackCure")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(private.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=days))
            .add_extension(x509.SubjectAlternativeName(names), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .sign(private, hashes.SHA256()))
    key.write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    try:
        key.chmod(0o600)
    except OSError:
        pass
    return crt, key


def main() -> int:
    ap = argparse.ArgumentParser(description="Certificat TLS auto-signé pour Hospital Copilot")
    ap.add_argument("--dir", default=str(DEFAULT_DIR))
    ap.add_argument("--host", action="append", default=[], help="nom DNS ou adresse IP supplémentaire (répétable)")
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--force", action="store_true", help="remplacer un certificat existant")
    a = ap.parse_args()
    try:
        crt, key = make_cert(Path(a.dir), a.host, a.days, a.force)
    except ImportError:
        print("Bibliothèque « cryptography » absente : pip install cryptography", file=sys.stderr)
        return 1
    print(f"Certificat : {crt}\nClé privée : {key}\nDans .env : HTTPS=true  (TLS_CERT_FILE / TLS_KEY_FILE si un autre emplacement est utilisé)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
