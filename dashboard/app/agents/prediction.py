"""
PredictionAgent (V2, étape 8) — prédiction des crises.

Pour chaque patient hospitalisé, estime un risque (0–100) et une fenêtre de temps approximative avant la crise
pour 5 conditions (épilepsie, sepsis, événement cardiaque, détérioration générale, complications du diabète).
Les scores sont calculés par `clinical/prediction.predict` (règles + extrapolation des tendances). Le workflow n8n
`crisis-prediction` rédige l'explication et la conduite à tenir. Alertes graduées : infirmiers à partir de
« élevé », médecin de garde à « critique ». Estimation de prototype, non validée cliniquement.
"""

from __future__ import annotations

import json
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import select

from .. import care, orchestration
from ..bus import Event, bus
from ..clinical import prediction as rules
from ..config import settings
from ..db import session_scope
from ..ingest import handler
from ..models import Patient, Prediction
from ..notify import notify
from ..ws import manager
from .base import Agent

ORDER = {"faible": 0, "modéré": 1, "élevé": 2, "critique": 3}
ANTIEPILEPTICS = ("lévétiracétam", "levetiracetam", "valpro", "carbamaz", "lamotrigine")
SERIES = {"hr": ("ecg", "hr"), "rr": ("ecg", "rr"), "st": ("ecg", "stMm"), "sys": ("bp", "sys"), "spo2": ("spo2", "spo2"), "tempC": ("thermometer", "tempC"), "glucose": ("glucometer", "glucose")}
DISCLAIMER = "Estimation de prototype, non validée cliniquement."
esc = lambda t: str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731


def prediction_out(p: Prediction) -> dict[str, Any]:
    ts = p.ts if p.ts.tzinfo else p.ts.replace(tzinfo=timezone.utc)
    return {"id": p.id, "key": p.key, "label": rules.LABELS.get(p.key, p.key), "risk": p.risk, "level": p.level, "window": json.loads(p.window_json) if p.window_json else None, "confidence": p.confidence,
            "factors": json.loads(p.factors_json or "[]"), "ai": json.loads(p.ai_json) if p.ai_json else None, "ts": ts.isoformat()}


class PredictionAgent(Agent):
    name = "PredictionAgent"
    description = "Estime le risque et la fenêtre de temps avant une crise (épilepsie, sepsis, cardiaque, détérioration, diabète) par règles et extrapolation des tendances. Prototype non validé cliniquement."
    patterns = ["internal/reset"]

    def __init__(self) -> None:
        super().__init__()
        self.tick_interval = settings.prediction_tick_s
        self.news2: dict[str, deque] = {}
        self.current: dict[str, dict[str, dict[str, Any]]] = {}  # chambre → condition → dernière prédiction
        self.stored: dict[tuple[str, str], tuple[int, str]] = {}

    async def handle(self, ev: Event) -> None:
        self.news2.clear()
        self.current.clear()
        self.stored.clear()

    def context(self, s, room: str) -> Optional[dict[str, Any]]:
        ctx = care.clinical_context(s, room)
        if not ctx or not ctx["patient_pk"]:
            return None
        series = {k: handler.device_history(f"{room}-{dev}", metric, 600) for k, (dev, metric) in SERIES.items()}
        q = self.news2.setdefault(room, deque(maxlen=400))
        if ctx["news2"] is not None:
            q.append((time.time(), float(ctx["news2"])))
        series["news2"] = list(q)
        rs = handler.room_state(room)
        from . import manager as agents

        psy = agents.get("PsychAgent")
        missed = [d for d in care.missed_doses(s, ctx["patient_pk"]) if any(k in d.label.lower() for k in ANTIEPILEPTICS)]
        ctx.update(series=series, kp_variance=rs.get("kpVariance"), rhythmic_hz=rs.get("rhythmicHz"), sleep_hours=psy.sig(room).sleep_hours() if psy else None, missed_antiepileptic=len(missed))
        return ctx

    def risk_of(self, room: str, key: str) -> Optional[int]:
        cur = self.current.get(room, {}).get(key)
        return cur["risk"] if cur else None

    async def on_tick(self) -> None:
        for room in handler.ROOMS:
            await self.evaluate(room)

    async def evaluate(self, room: str) -> None:
        events: list[tuple[dict[str, Any], str, int]] = []
        with session_scope() as s:
            ctx = self.context(s, room)
            if not ctx:
                return
            preds = rules.predict(ctx)
            cur = self.current.setdefault(room, {})
            changed = False
            for p in preds:
                prev = self.stored.get((room, p["key"]))
                cur[p["key"]] = p
                if prev and abs(prev[0] - p["risk"]) < 5 and prev[1] == p["level"]:
                    continue
                self.stored[(room, p["key"])] = (p["risk"], p["level"])
                changed = True
                row = Prediction(patient_pk=ctx["patient_pk"], admission_id=ctx["admission_id"], room_code=room, key=p["key"], risk=p["risk"], level=p["level"], confidence=p["confidence"],
                                 window_json=json.dumps(p["window"], ensure_ascii=False) if p["window"] else "", factors_json=json.dumps(p["factors"], ensure_ascii=False))
                s.add(row)
                s.flush()
                p["id"] = row.id
                if ORDER[p["level"]] >= 2 and (not prev or ORDER[p["level"]] > ORDER[prev[1]]):
                    events.append((p, prev[1] if prev else "faible", row.id))
            pid, name = ctx["patient_id"], ctx["name"]
            llm_ctx = {"chambre": room, "patient": {"nom": name, "age": ctx["age"], "antecedents": ctx["history"], "allergies": ctx["allergies"] or "aucune connue"}, "traitements_en_cours": ctx["treatments"],
                       "constantes": ctx["vitals"], "news2": ctx["news2"], "qsofa": ctx["qsofa"]}
        if changed:
            await manager.broadcast({"type": "predictions", "room": room, "patient_id": pid, "predictions": [{k: v for k, v in p.items()} for p in preds]})
        for p, before, row_id in events:
            win = p["window"]["text"] if p["window"] else "fenêtre non estimable"
            title = f"Prédiction — {p['label']} : risque {p['level']}, chambre {room}"
            body = f"{name} : risque {p['risk']}/100, crise estimée dans {win} (confiance {p['confidence']}). Facteurs : {'; '.join(p['factors'][:4])}. {DISCLAIMER}"
            await notify("critical" if p["level"] == "critique" else "warning", title, body, room=room, target_role="nurse", telegram=False)
            if p["level"] == "critique":
                await notify("critical", f"Médecin de garde — {title}", body, room=room, target_role="duty_doctor", telegram=False)
            await bus.publish("internal/risk_candidate", {"room": room, "type": rules.RISK_TYPES[p["key"]], "source_agent": self.name,
                                                          "details": {"risk": p["risk"], "level": p["level"], "window": win, "confidence": p["confidence"], "factors": p["factors"][:5]}})
            path = await orchestration.ask("crisis-prediction", str(row_id), {"task": "crisis_prediction", **llm_ctx, "condition": p["label"], "risque": p["risk"], "niveau": p["level"], "fenetre_estimee": win,
                                                                               "confiance": p["confidence"], "facteurs": p["factors"]}, room=room)
            await self.log(room, input=f"{p['label']} : risque {p['risk']}/100 ({before} → {p['level']}), fenêtre {win}", reasoning=f"Score déterministe — facteurs : {'; '.join(p['factors'][:5])}. Confiance {p['confidence']}. "
                           + ("Infirmiers et médecin de garde alertés." if p["level"] == "critique" else "Infirmiers alertés.") + (" Explication demandée au workflow n8n crisis-prediction." if path == "n8n" else " Explication demandée au LLM local.") + f" {DISCLAIMER}",
                           output=f"alerte {p['level']} — crise estimée dans {win}", status="error")


@orchestration.handler("crisis-prediction")
async def on_prediction_explanation(ref: str, result: dict[str, Any], meta: dict[str, Any]) -> Optional[str]:
    with session_scope() as s:
        row = s.get(Prediction, int(ref))
        if not row:
            return None
        ai = {"explanation": str(result.get("explanation") or "")[:1200], "conduct": [str(x)[:260] for x in (result.get("conduct") or [])][:5], "provider": meta.get("provider") or "anthropic (n8n)", "fallback": bool(meta.get("fallback"))}
        row.ai_json = json.dumps(ai, ensure_ascii=False)
        s.flush()
        p = s.get(Patient, row.patient_pk)
        out, pid, room, name = prediction_out(row), p.patient_id, row.room_code, p.full_name
    from . import manager as agents

    agent = agents.get("PredictionAgent")
    if agent and room in agent.current and out["key"] in agent.current[room]:
        agent.current[room][out["key"]]["ai"] = ai
    await manager.broadcast({"type": "predictions", "event": "explanation", "room": room, "patient_id": pid, "prediction": out})
    win = out["window"]["text"] if out["window"] else "fenêtre non estimable"
    return (f"🔮 <b>Prédiction — {esc(out['label'])}</b> · chambre {esc(room)}\n{esc(name)} : risque <b>{out['risk']}/100</b> ({out['level']}), crise estimée dans <b>{esc(win)}</b> (confiance {out['confidence']}).\n"
            f"{esc(ai['explanation'])}\n" + "\n".join(f"• {esc(c)}" for c in ai["conduct"]) + f"\n<i>{DISCLAIMER} {orchestration.DISCLAIMER}</i>")
