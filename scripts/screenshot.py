"""
Capture headless (Playwright/Chromium) du tableau de bord : non-régression 3D + vues HTML.

    python scripts/screenshot.py --url http://localhost:8000 --out docs/screenshots [--views twin,devices,...]

Se connecte en `owner`, attend le WebSocket et le canvas Three.js, capture chaque vue,
et échoue (code 1) si une erreur JS (pageerror / console.error) est détectée.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

DEFAULT_VIEWS = ["twin", "devices", "staff", "pharmacy", "cameras", "detection", "command", "patients", "shift", "report", "prescription", "history", "users"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--out", default="docs/screenshots")
    ap.add_argument("--user", default="owner")
    ap.add_argument("--password", default="hackcure2026")
    ap.add_argument("--views", default=",".join(DEFAULT_VIEWS))
    ap.add_argument("--wait", type=float, default=4.0, help="secondes d'attente après l'init 3D")
    ap.add_argument("--scenario", default=None, help="scénario à lancer avant la capture 'twin-scenario'")
    ap.add_argument("--scenario-wait", type=float, default=20.0)
    ap.add_argument("--poses", action="store_true", help="capture des postures étendues (sim embarqué requis)")
    ap.add_argument("--legacy-fall", action="store_true", help="déclenche le bouton de démo existant (chute patient_02) et capture")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    ignored = ("favicon", "net::ERR_", "Failed to load resource", "WebGL", "GPU stall", "THREE.WebGLRenderer: Context Lost")

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"])
        page = browser.new_page(viewport={"width": 1600, "height": 900})
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" and not any(s in m.text for s in ignored) else None)

        page.goto(f"{args.url}/login", wait_until="domcontentloaded")
        page.fill("#username", args.user)
        page.fill("#password", args.password)
        page.click("#login-btn")
        page.wait_for_url(f"{args.url}/**", timeout=15000)
        page.wait_for_selector("#three-container canvas", timeout=30000)
        page.wait_for_function("document.getElementById('connection-status').className === 'status-connected'", timeout=15000)
        time.sleep(args.wait)
        page.screenshot(path=str(out / "01-twin.png"))
        print("captured twin")

        # zoom chambre 101 (bouton existant ajouté par scene.js)
        try:
            page.click("#camera-controls button[title='Zoom to room 101']", timeout=3000, force=True)
            time.sleep(1.5)
            page.screenshot(path=str(out / "02-room101.png"))
            print("captured room101")
        except Exception as exc:
            print("zoom 101 skipped:", exc)

        if args.scenario:
            page.evaluate(f"fetch('/api/demo/scenario', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify({{name:'{args.scenario}'}})}})")
            time.sleep(args.scenario_wait)
            page.screenshot(path=str(out / f"03-scenario-{args.scenario}.png"))
            print("captured scenario", args.scenario)
            # panneau agents
            page.screenshot(path=str(out / f"03b-agents-{args.scenario}.png"), clip={"x": 1290, "y": 56, "width": 310, "height": 844})

        if args.legacy_fall:
            page.evaluate("fetch('/api/demo/trigger', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({patient_id:'patient_02', event_type:'fall_and_pain', confidence:0.9})})")
            time.sleep(2.5)
            page.click("#camera-controls button[title='Zoom to room 102']", timeout=3000, force=True)
            time.sleep(1.5)
            page.screenshot(path=str(out / "04-legacy-fall-102.png"))
            page.evaluate("fetch('/api/demo/trigger', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({patient_id:'patient_02', event_type:'recover', confidence:0.9})})")
            print("captured legacy fall")

        if args.poses:
            cases = [("102", "sitting_bed", "awake_bed"), ("102", "sitting_chair", "out_of_bed"), ("103", "standing", "out_of_bed"),
                     ("103", "walking", "out_of_bed"), ("104", "absent", "toilet"), ("104", "on_floor", "fall")]
            for n, (room, posture, activity) in enumerate(cases, start=5):
                body = json.dumps({"room": room, "action": "posture", "params": {"posture": posture, "activity": activity}})
                page.evaluate(f"fetch('/api/demo/sim/action', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: '{body}'}})")
                time.sleep(3.0)
                page.click(f"#camera-controls button[title='Zoom to room {room}']", timeout=3000, force=True)
                time.sleep(1.5)
                page.screenshot(path=str(out / f"0{n}-pose-{posture}-{room}.png"))
                print("captured pose", posture)
            for room in ("102", "103", "104"):
                page.evaluate(f"fetch('/api/demo/sim/action', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify({{room:'{room}', action:'recover', params:{{}}}})}})")
            page.click("#btn-overview", force=True)

        for i, view in enumerate([v for v in args.views.split(",") if v and v != "twin"], start=10):
            btn = page.query_selector(f"#main-nav .nav-btn[data-view='{view}']")
            if not btn or btn.is_disabled():
                print("view skipped (absent/disabled):", view)
                continue
            btn.click()
            time.sleep(1.8)
            page.screenshot(path=str(out / f"{i}-{view}.png"))
            print("captured", view)
        page.keyboard.press("Escape")
        time.sleep(0.5)
        page.screenshot(path=str(out / "99-twin-after.png"))
        browser.close()

    (out / "console-errors.json").write_text(json.dumps(errors, indent=2, ensure_ascii=False), encoding="utf-8")
    if errors:
        print(f"\n{len(errors)} erreur(s) JS :")
        for e in errors[:20]:
            print("  -", e[:300])
        return 1
    print("\nAucune erreur JS.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
