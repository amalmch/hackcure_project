"""Telecharge le modele FER+ ONNX (ONNX Model Zoo, licence MIT) dans edge/models/ferplus.onnx."""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

URLS = [
    "https://github.com/onnx/models/raw/main/validated/vision/body_analysis/emotion_ferplus/model/emotion-ferplus-8.onnx",
    "https://github.com/onnx/models/raw/main/vision/body_analysis/emotion_ferplus/model/emotion-ferplus-8.onnx",
]
DEST = Path(__file__).resolve().parent / "models" / "ferplus.onnx"


def main() -> int:
    DEST.parent.mkdir(parents=True, exist_ok=True)
    for url in URLS:
        try:
            print("Telechargement", url)
            urllib.request.urlretrieve(url, DEST)
            print("OK ->", DEST, DEST.stat().st_size // 1024, "ko")
            return 0
        except Exception as exc:
            print("echec:", exc)
    print("Modele indisponible : l expression restera neutral / 0 (fonctionnement degrade accepte).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
