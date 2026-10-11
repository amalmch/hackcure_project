"""Sonde de santé (Docker HEALTHCHECK) : code 0 si GET /health répond « ok », en HTTP ou en HTTPS (certificat auto-signé accepté)."""

from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.request


def main() -> int:
    https = os.getenv("HTTPS", "").strip().lower() in ("1", "true", "yes", "on")
    url = f"{'https' if https else 'http'}://127.0.0.1:{os.getenv('PORT', '8000')}/health"
    ctx = ssl._create_unverified_context() if https else None  # sonde locale : le certificat de démo est auto-signé
    try:
        with urllib.request.urlopen(url, timeout=4, context=ctx) as r:
            return 0 if r.status == 200 and json.load(r).get("status") == "ok" else 1
    except Exception as exc:
        print(f"healthcheck: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
