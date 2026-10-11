"""
Calibration des zones (lit, porte des toilettes, sortie) : on dessine les polygones à la souris sur une image figée.

    python edge/calibrate_zones.py --source 0            # capture une image de la caméra
    python edge/calibrate_zones.py --image photo.jpg     # ou une image existante

Touches : clic gauche = ajouter un point · n = polygone suivant (bed → bathroom_door → exit) · z = annuler le dernier point
          s = sauvegarder dans edge/config/room101.yaml · q = quitter sans sauvegarder.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

ORDER = ["bed", "bathroom_door", "exit"]
COLORS = {"bed": (255, 160, 60), "bathroom_door": (60, 200, 255), "exit": (80, 80, 255)}


def main() -> None:
    import cv2

    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="0")
    ap.add_argument("--image", default=None)
    ap.add_argument("--config", default=str(Path(__file__).parent / "config" / "room101.yaml"))
    args = ap.parse_args()

    if args.image:
        frame = cv2.imread(args.image)
    else:
        cap = cv2.VideoCapture(int(args.source) if args.source.isdigit() else args.source)
        ok, frame = cap.read()
        cap.release()
        if not ok:
            raise SystemExit("Impossible de capturer une image")
    h, w = frame.shape[:2]
    polys: dict[str, list[tuple[float, float]]] = {k: [] for k in ORDER}
    idx = [0]

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            polys[ORDER[idx[0]]].append((round(x / w, 3), round(y / h, 3)))

    cv2.namedWindow("calibration")
    cv2.setMouseCallback("calibration", on_mouse)
    while True:
        img = frame.copy()
        for name, pts in polys.items():
            px = [(int(x * w), int(y * h)) for x, y in pts]
            for i, p in enumerate(px):
                cv2.circle(img, p, 4, COLORS[name], -1)
                if i:
                    cv2.line(img, px[i - 1], p, COLORS[name], 2)
            if len(px) > 2:
                cv2.line(img, px[-1], px[0], COLORS[name], 1)
            if px:
                cv2.putText(img, name, px[0], cv2.FONT_HERSHEY_SIMPLEX, 0.6, COLORS[name], 2)
        cv2.putText(img, f"Polygone courant : {ORDER[idx[0]]}  (n suivant, z annuler, s sauver, q quitter)", (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
        cv2.imshow("calibration", img)
        k = cv2.waitKey(30) & 0xFF
        if k == ord("q"):
            break
        if k == ord("n"):
            idx[0] = (idx[0] + 1) % len(ORDER)
        if k == ord("z") and polys[ORDER[idx[0]]]:
            polys[ORDER[idx[0]]].pop()
        if k == ord("s"):
            cfg_path = Path(args.config)
            cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            cfg.setdefault("zones", {})
            for name, pts in polys.items():
                if len(pts) >= 3:
                    cfg["zones"][name] = [list(p) for p in pts]
            cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
            print("Zones enregistrées dans", cfg_path)
            break
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
