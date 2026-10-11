"""
Captures Playwright de la V2 : chaque capture exécute un fragment JavaScript puis photographie la page.

    python scripts/shots_v2.py --url http://localhost:8010 --out docs/screenshots/v2 \
        --shot "00-rdc=HospitalFloors.setMode('rdc')" --shot "01-etage=HospitalFloors.setMode('etage')"

Options par capture : préfixe `user@` pour changer de compte (ex. `medecin@nom=js`), `--wait` secondes après le JS.
Échoue (code 1) si une erreur JavaScript est levée par la page.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

IGNORED = ("favicon", "net::ERR_", "Failed to load resource", "WebGL", "GPU stall", "Context Lost")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8010")
    ap.add_argument("--out", default="docs/screenshots/v2")
    ap.add_argument("--user", default="owner")
    ap.add_argument("--password", default="hackcure2026")
    ap.add_argument("--wait", type=float, default=2.5)
    ap.add_argument("--shot", action="append", default=[], help="[user@]nom=javascript")
    ap.add_argument("--path", default="/", help="page à ouvrir après connexion")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from playwright.sync_api import sync_playwright

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    by_user: dict[str, list[tuple[str, str]]] = {}
    for spec in args.shot:
        head, js = spec.split("=", 1)
        user, name = head.split("@", 1) if "@" in head else (args.user, head)
        by_user.setdefault(user, []).append((name, js))

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for user, shots in by_user.items():
            ctx = browser.new_context(viewport={"width": 1600, "height": 900})
            page = ctx.new_page()
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            page.on("console", lambda m: errors.append(f"console: {m.text}") if m.type == "error" and not any(i in m.text for i in IGNORED) else None)
            r = page.request.post(args.url + "/api/auth/login", data={"username": user, "password": args.password})
            if not r.ok:
                errors.append(f"connexion {user}: HTTP {r.status}")
                continue
            page.goto(args.url + args.path)
            page.wait_for_load_state("networkidle", timeout=20000)
            time.sleep(4)
            for name, js in shots:
                try:
                    result = page.evaluate(f"(async () => {{ {js} }})()") if js.strip() else None
                except Exception as exc:  # erreur du fragment : comptée comme erreur JS
                    errors.append(f"{name}: {exc}")
                    result = None
                time.sleep(args.wait)
                page.screenshot(path=str(out / f"{name}.png"))
                print(f"  {name}.png" + (f"  → {result}" if result is not None else ""))
            ctx.close()
        browser.close()
    for e in errors:
        print("ERREUR JS :", e)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
