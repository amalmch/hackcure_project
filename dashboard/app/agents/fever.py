"""
FeverAgent (V2, étape 3) — fièvre vraie ≠ simple hausse thermique.

- Lit le thermomètre (température **centrale**) de chaque chambre et applique `clinical/fever.assess` :
  * **fièvre vraie** ⇒ risque « Fièvre » (sévérité fixée par le RiskAgent) + **parcours fièvre** :
    1. bilan clinique — le médecin de garde est demandé, checklist d'examen ;
    2. bilan biologique — proposé par des règles à partir du dossier, justifié par le LLM (workflow n8n
       `fever-pathway`), **validé par le médecin**, résultats simulés versés au dossier médical ;
    3. ensuite seulement, mesure de **confort** par l'EnvironmentAgent ;
    4. résolution par la boucle soignant (antipyrétique prescrit, revérification de la température centrale).
  * **simple hausse thermique** (peau ou ambiance chaude, température centrale normale) ⇒ pas de médecin,
    pas de bilan : l'EnvironmentAgent agit directement et revérifie ; simple trace dans le journal.
- La température cutanée de la caméra thermique ne déclare jamais une fièvre à elle seule.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlmodel import select

from .. import orchestration
from ..bus import Event, bus
from ..clinical import fever as rules
from ..clinical import labs
from ..config import settings
from ..db import session_scope
from ..ingest import handler
from ..models import FeverPathway, LabResult, MedicalRecordEntry, Risk
from ..notify import notify
from ..ws import manager
from .base import Agent
from .context import current_news2, room_vitals

HOLD_STAGES = ("clinical_exam", "lab_proposed")  # tant que le bilan n'est pas validé, pas de réglage de confort
hold_rooms: set[str] = set()  # chambres où l'EnvironmentAgent doit attendre
STAGE_LABELS = {"clinical_exam": "Bilan clinique en cours", "lab_proposed": "Bilan biologique à valider", "lab_ordered": "Bilan prélevé — résultats attendus",
                "lab_results": "Résultats reçus — traitement et surveillance", "resolved": "Résolu"}


def pathway_dict(p: FeverPathway) -> dict[str, Any]:
    iso = lambda d: d.isoformat() if d else None  # noqa: E731
    return {
        "id": p.id, "risk_id": p.risk_id, "room": p.room_code, "stage": p.stage, "stage_label": STAGE_LABELS.get(p.stage, p.stage), "criterion": p.criterion,
        "core_temp": p.core_temp, "qsofa": p.qsofa, "news2": p.news2, "checklist": json.loads(p.checklist_json or "[]"), "labs": json.loads(p.labs_json or "[]"),
        "results": json.loads(p.results_json or "[]"), "ai": json.loads(p.ai_json or "{}"), "exam_done_by": p.exam_done_by, "exam_done_at": iso(p.exam_done_at),
        "labs_validated_by": p.labs_validated_by, "labs_validated_at": iso(p.labs_validated_at), "results_due_at": iso(p.results_due_at), "results_at": iso(p.results_at),
        "comfort_note": p.comfort_note, "record_entry_id": p.record_entry_id, "created_at": iso(p.created_at), "closed_at": iso(p.closed_at),
        "disclaimer": orchestration.DISCLAIMER,
    }


async def broadcast(p: dict[str, Any], event: str = "updated") -> None:
    await manager.broadcast({"type": "fever", "event": event, "pathway": p})


def _refresh_hold() -> None:
    with session_scope() as s:
        rows = s.exec(select(FeverPathway.room_code).where(FeverPathway.stage.in_(HOLD_STAGES))).all()
    hold_rooms.clear()
    hold_rooms.update(rows)


def _context(s, p: FeverPathway, phase: str) -> dict[str, Any]:
    from ..risks import patient_context

    ctx = patient_context(s, p.room_code)
    pat = ctx.get("patient") or {}
    v = room_vitals(p.room_code)
    last: dict[str, Any] = {}
    if p.patient_pk:
        for r in s.exec(select(LabResult).where(LabResult.patient_pk == p.patient_pk).order_by(LabResult.date.desc()).limit(120)).all():
            last.setdefault(r.code, {"examen": r.label, "valeur": r.value if r.value is not None else r.text, "unite": r.unit, "date": r.date.date().isoformat(), "anormal": r.abnormal})
    return {
        "task": "fever_pathway", "phase": phase, "chambre": p.room_code, "critere": p.criterion, "qsofa": p.qsofa, "news2": p.news2,
        "patient": {"nom": pat.get("full_name"), "age": pat.get("age"), "sexe": pat.get("sex"), "allergies": pat.get("allergies") or "aucune connue", "antecedents": pat.get("history")},
        "traitements_en_cours": ctx.get("treatments") or "aucun",
        "constantes": {k: v.get(k) for k in ("tempC", "hr", "rr", "sys", "dia", "spo2") if v.get(k) is not None},
        "temperature_cutanee": handler.room_state(p.room_code).get("skinTempC"),
        "bilan_propose": [{"code": x["code"], "examen": x["label"], "motif": x.get("motif")} for x in json.loads(p.labs_json or "[]")],
        "dernieres_valeurs_du_dossier": last,
        "catalogue": sorted(labs.CATALOG),
        "resultats": [{"examen": r["label"], "valeur": r["value"] if r["value"] is not None else r["text"], "unite": r["unit"], "normes": labs.norm_text(r["code"]), "anormal": r["abnormal"]}
                      for r in json.loads(p.results_json or "[]")] if phase == "resultats" else [],
    }


# ─── résultat du raisonnement LLM (n8n `fever-pathway` ou repli local) ────────
@orchestration.handler("fever-pathway")
async def on_llm_result(ref: str, result: dict[str, Any], meta: dict[str, Any]) -> Optional[str]:
    with session_scope() as s:
        p = s.get(FeverPathway, int(ref))
        if not p:
            return None
        ai = json.loads(p.ai_json or "{}")
        phase = "resultats" if p.stage in ("lab_results", "resolved") and result.get("interpretation") else "bilan"
        ai[phase] = {"summary": str(result.get("summary") or "")[:1200], "exam_focus": [str(x)[:300] for x in (result.get("exam_focus") or [])][:6],
                     "interpretation": str(result.get("interpretation") or "")[:1500], "watch": [str(x)[:300] for x in (result.get("watch") or [])][:6],
                     "provider": meta.get("provider") or "anthropic (n8n)", "fallback": bool(meta.get("fallback"))}
        p.ai_json = json.dumps(ai, ensure_ascii=False)
        if phase == "bilan":
            items = json.loads(p.labs_json or "[]")
            by_code = {x["code"]: x for x in items}
            for x in result.get("labs") or []:
                code = str((x or {}).get("code") or "").upper()
                why = str((x or {}).get("justification") or "").strip()[:400]
                if code in by_code:
                    if why:
                        by_code[code]["justification"] = why
                elif code in labs.CATALOG and why:  # suggestion du LLM : jamais cochée d'office
                    items.append({"code": code, "label": labs.label(code), "motif": "", "justification": why, "selected": False, "source": "suggestion IA"})
            p.labs_json = json.dumps(items, ensure_ascii=False)
        p.updated_at = datetime.now(timezone.utc)
        s.flush()
        d = pathway_dict(p)
        room, risk_id = p.room_code, p.risk_id
        summary = ai[phase]["summary"]
        lab_names = ", ".join(x["label"] for x in json.loads(p.labs_json) if x.get("selected"))
    await broadcast(d)
    esc = lambda t: str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
    if phase == "bilan":
        return (f"🌡️ <b>Fièvre vraie — médecin de garde demandé</b>\nChambre <b>{room}</b> · risque #{risk_id}\n{esc(summary)}\n\n"
                f"<b>1. Bilan clinique</b> : checklist à compléter dans la plateforme.\n<b>2. Bilan biologique proposé</b> (à valider) : {esc(lab_names)}\n\n<i>{orchestration.DISCLAIMER}</i>")
    return f"🧪 <b>Résultats du bilan — chambre {room}</b>\n{esc(summary)}\n{esc(d['ai'][phase]['interpretation'])}\n\n<i>{orchestration.DISCLAIMER}</i>"


class FeverAgent(Agent):
    name = "FeverAgent"
    description = "Distingue la fièvre vraie (température centrale) d'une simple hausse thermique et pilote le parcours fièvre : bilan clinique, bilan biologique, confort, résolution."
    patterns = ["hackcure/room/+/device/+", "internal/risk/created", "internal/reset"]
    tick_interval = 2.0

    def __init__(self) -> None:
        super().__init__()
        self.reported: dict[str, float] = {}
        self.rise_logged: dict[str, float] = {}

    async def on_start(self) -> None:
        try:
            _refresh_hold()
        except Exception:
            pass

    async def handle(self, ev: Event) -> None:
        if ev.topic == "internal/reset":
            self.reported.clear()
            self.rise_logged.clear()
            return
        if ev.topic == "internal/risk/created":
            if ev.payload.get("type") == "fever":
                await self.open_pathway(int(ev.payload["risk_id"]), str(ev.payload["room"]))
            return
        d = ev.payload["data"]
        if d.get("type") != "thermometer" or (d.get("metrics") or {}).get("tempC") is None:
            return
        room = ev.payload["room"]
        rs = handler.room_state(room)
        now = time.time()
        a = rules.assess(handler.device_history(f"{room}-thermometer", "tempC", 3600), now, skin_temp=rs.get("skinTempC"), env_temp=(rs.get("env") or {}).get("tempC"),
                         repeat_gap_s=settings.fever_repeat_gap_s)
        if a["kind"] == "fever":
            if now - self.reported.get(room, 0) < 120:
                return
            self.reported[room] = now
            v = room_vitals(room)
            q = rules.qsofa(v.get("rr"), v.get("sys"))
            n2 = current_news2(room)
            async with self.working("acting"):
                await self.log(room, input=f"thermomètre {a['core']:.1f} °C, caméra thermique {a['skin']} °C, chambre {a['env']} °C",
                               reasoning=f"FIÈVRE VRAIE : {a['criterion']}. qSOFA {q['score']}/3, NEWS2 {n2.score if n2 else 'n/a'}. La température cutanée seule n'aurait pas suffi.",
                               output="risque candidat « Fièvre » → parcours fièvre (médecin de garde, bilan clinique puis biologique)")
                await bus.publish("internal/risk_candidate", {"room": room, "type": "fever", "source_agent": self.name,
                                                              "details": {"tempC": a["core"], "criterion": a["criterion"], "skinTempC": a["skin"], "qsofa": q["score"], "hr": v.get("hr"), "rr": v.get("rr")}})
        elif a["kind"] == "thermal_rise":
            self.reported.pop(room, None)
            if now - self.rise_logged.get(room, 0) < 300:
                return
            self.rise_logged[room] = now
            await self.on_thermal_rise(room, a)
        else:
            if self.reported.pop(room, None) is not None:
                await bus.publish("internal/risk_clear", {"room": room, "types": ["fever"], "reason": f"température centrale {a['core']:.1f} °C"})

    # ── simple hausse thermique : pas de médecin, pas de bilan ───────────────
    async def on_thermal_rise(self, room: str, a: dict[str, Any]) -> None:
        from . import manager as agents

        env_agent = agents.get("EnvironmentAgent")
        async with self.working("acting"):
            await self.log(room, input=f"thermomètre {a['core'] if a['core'] is not None else '—'} °C, caméra thermique {a['skin']} °C, chambre {a['env']} °C",
                           reasoning=f"SIMPLE HAUSSE THERMIQUE, pas de fièvre : {a['criterion']}. Ni médecin ni bilan : mesure d'ambiance confiée à l'EnvironmentAgent, puis revérification.",
                           output="EnvironmentAgent sollicité (confort)")
        if env_agent is not None:
            await env_agent.thermal_rise(room, a)

    # ── parcours fièvre ──────────────────────────────────────────────────────
    async def open_pathway(self, risk_id: int, room: str) -> None:
        from ..risks import patient_context

        with session_scope() as s:
            if s.exec(select(FeverPathway).where(FeverPathway.risk_id == risk_id)).first():
                return
            risk = s.get(Risk, risk_id)
            ctx = patient_context(s, room)
            pat = ctx.get("patient") or {}
            v = room_vitals(room)
            q = rules.qsofa(v.get("rr"), v.get("sys"))
            n2 = current_news2(room)
            proposal = labs.propose_fever_workup(pat, ctx.get("treatments") or "", v, q["score"], has_iv=v.get("ivVolumeLeftMl") is not None)
            checklist = [{"key": k, "label": lbl, "done": False, "by": None, "at": None, "note": ""} for k, lbl in rules.CHECKLIST]
            for item in checklist:
                if item["key"] == "sepsis":
                    item["note"] = f"qSOFA {q['score']}/3 (FR ≥ 22 : {'oui' if q['items']['fr_ge_22'] else 'non'}, PAS ≤ 100 : {'oui' if q['items']['pas_le_100'] else 'non'}) · NEWS2 {n2.score if n2 else 'n/a'}"
                if item["key"] == "allergies":
                    item["note"] = f"Allergies : {pat.get('allergies') or 'aucune connue'} · Traitements : {ctx.get('treatments') or 'aucun'}"
            from ..models import Patient

            pk = s.exec(select(Patient.id).where(Patient.patient_id == pat.get("patient_id"))).first() if pat.get("patient_id") else None
            crit = ""
            if risk and "criterion" in (risk.notes or ""):
                crit = risk.notes
            p = FeverPathway(risk_id=risk_id, admission_id=ctx.get("admission_id"), patient_pk=pk, room_code=room, stage="clinical_exam",
                             criterion=crit or f"température centrale {v.get('tempC')} °C", core_temp=v.get("tempC"), qsofa=q["score"], news2=n2.score if n2 else None,
                             checklist_json=json.dumps(checklist, ensure_ascii=False), labs_json=json.dumps(proposal, ensure_ascii=False))
            a = rules.assess(handler.device_history(f"{room}-thermometer", "tempC", 3600), time.time(), repeat_gap_s=settings.fever_repeat_gap_s)
            if a["kind"] == "fever":
                p.criterion = a["criterion"]
            s.add(p)
            s.flush()
            pid, d = p.id, pathway_dict(p)
            context = _context(s, p, "bilan")
            name = pat.get("full_name") or "Patient"
        hold_rooms.add(room)
        await broadcast(d, "created")
        # 1) le médecin de garde est demandé (Telegram envoyé par le workflow, ou par le repli)
        await notify("warning", f"Médecin de garde demandé — fièvre vraie, chambre {room}", f"{name} · {d['criterion']} · qSOFA {d['qsofa']}/3. Bilan clinique à réaliser (checklist), puis validation du bilan biologique proposé.",
                     room=room, risk_id=risk_id, target_role="duty_doctor", telegram=False)
        path = await orchestration.ask("fever-pathway", str(pid), context, room=room, risk_id=risk_id)
        await self.log(room, input=f"risque #{risk_id} « Fièvre » créé", reasoning=f"Parcours fièvre #{pid} ouvert : médecin de garde demandé ; checklist d'examen clinique ({len(rules.CHECKLIST)} points) ; "
                       f"bilan biologique proposé par règles ({len(d['labs'])} examens) ; justification demandée " + ("au workflow n8n fever-pathway." if path == "n8n" else "au LLM local (n8n indisponible).")
                       + " L'EnvironmentAgent attend la validation du bilan avant tout réglage de confort.",
                       output="étape 1/4 : bilan clinique", risk_id=risk_id)

    async def on_tick(self) -> None:
        now = datetime.now(timezone.utc)
        due: list[int] = []
        closed: list[dict[str, Any]] = []
        with session_scope() as s:
            for p in s.exec(select(FeverPathway).where(FeverPathway.stage != "resolved")).all():
                risk = s.get(Risk, p.risk_id)
                if risk is None or risk.status == "resolved":
                    p.stage, p.closed_at, p.updated_at = "resolved", now, now
                    s.flush()
                    closed.append(pathway_dict(p))
                elif p.stage == "lab_ordered" and p.results_due_at is not None:
                    d = p.results_due_at if p.results_due_at.tzinfo else p.results_due_at.replace(tzinfo=timezone.utc)
                    if d <= now:
                        due.append(p.id)
        for d in closed:
            hold_rooms.discard(d["room"])
            await broadcast(d, "resolved")
            await self.log(d["room"], input=f"risque #{d['risk_id']} résolu et vérifié", reasoning="La température centrale est revenue sous le seuil après l'intervention : parcours fièvre clos.", output=f"parcours #{d['id']} terminé", risk_id=d["risk_id"])
        for pid in due:
            await self.deliver_results(pid)

    async def deliver_results(self, pid: int) -> None:
        """Résultats biologiques simulés : versés au dossier médical, interprétés par le LLM."""
        now = datetime.now(timezone.utc)
        with session_scope() as s:
            p = s.get(FeverPathway, pid)
            if not p or p.stage != "lab_ordered":
                return
            codes = [x["code"] for x in json.loads(p.labs_json or "[]") if x.get("selected")]
            results = labs.simulate(codes, scenario="sepsis" if p.qsofa >= 2 else "infection", seed=p.id)
            if p.patient_pk:
                lines = "\n".join(f"- {r['label']} : {r['value'] if r['value'] is not None else r['text']} {r['unit']}".rstrip() + (f" (normes {labs.norm_text(r['code'])})" if r["value"] is not None else "") + (" ⚠" if r["abnormal"] else "") for r in results)
                entry = MedicalRecordEntry(patient_pk=p.patient_pk, admission_id=p.admission_id, type="biologie", date=now, title="Bilan biologique — fièvre",
                                           author=p.labs_validated_by or "médecin de garde", service="Laboratoire", facility="Clinique HackCure", source="plateforme",
                                           summary=f"{sum(1 for r in results if r['abnormal'])} valeur(s) hors normes sur {len(results)}", content=lines,
                                           data_json=json.dumps({"pathway_id": p.id, "risk_id": p.risk_id, "results": results}, ensure_ascii=False))
                s.add(entry)
                s.flush()
                p.record_entry_id = entry.id
                for r in results:
                    s.add(LabResult(patient_pk=p.patient_pk, entry_id=entry.id, code=r["code"], label=r["label"], value=r["value"], text=r["text"], unit=r["unit"], ref_low=r["ref_low"], ref_high=r["ref_high"], abnormal=r["abnormal"], date=now))
            p.results_json = json.dumps(results, ensure_ascii=False)
            p.stage, p.results_at, p.updated_at = "lab_results", now, now
            s.flush()
            d = pathway_dict(p)
            context = _context(s, p, "resultats")
            room, risk_id = p.room_code, p.risk_id
        await broadcast(d)
        abn = [r for r in d["results"] if r["abnormal"]]
        await notify("warning", f"Résultats du bilan — chambre {room}", f"{len(abn)} valeur(s) hors normes : " + ", ".join(f"{r['label']} {r['value']} {r['unit']}" for r in abn[:5]), room=room, risk_id=risk_id, target_role="duty_doctor", telegram=False)
        await orchestration.ask("fever-pathway", str(pid), context, room=room, risk_id=risk_id)
        await self.log(room, input=f"résultats du bilan (parcours #{pid}) : {len(d['results'])} examens", reasoning=f"Résultats simulés versés au dossier médical (document #{d['record_entry_id']}) ; {len(abn)} hors normes ; interprétation demandée au LLM.",
                       output="étape 4/4 : antipyrétique selon l'ordonnance, revérification de la température centrale", risk_id=risk_id)


# ─── actions des soignants (appelées par l'API) ──────────────────────────────
def set_check(pid: int, key: str, done: bool, note: Optional[str], by: str) -> dict[str, Any]:
    with session_scope() as s:
        p = s.get(FeverPathway, pid)
        if not p:
            raise KeyError(pid)
        items = json.loads(p.checklist_json or "[]")
        for it in items:
            if it["key"] == key:
                it["done"], it["by"], it["at"] = bool(done), by if done else None, datetime.now(timezone.utc).isoformat() if done else None
                if note is not None:
                    it["note"] = note[:400]
                break
        else:
            raise ValueError(key)
        p.checklist_json = json.dumps(items, ensure_ascii=False)
        p.updated_at = datetime.now(timezone.utc)
        s.flush()
        return pathway_dict(p)


def finish_exam(pid: int, by: str) -> dict[str, Any]:
    with session_scope() as s:
        p = s.get(FeverPathway, pid)
        if not p:
            raise KeyError(pid)
        if p.stage == "clinical_exam":
            p.stage, p.exam_done_by, p.exam_done_at = "lab_proposed", by, datetime.now(timezone.utc)
            p.updated_at = p.exam_done_at
        s.flush()
        return pathway_dict(p)


def validate_labs(pid: int, codes: Optional[list[str]], by: str) -> dict[str, Any]:
    """Le médecin valide le bilan (liste cochée, modifiable). Le bilan clinique doit être terminé."""
    now = datetime.now(timezone.utc)
    with session_scope() as s:
        p = s.get(FeverPathway, pid)
        if not p:
            raise KeyError(pid)
        if p.stage == "clinical_exam":
            raise PermissionError("Le bilan clinique doit être terminé avant de valider le bilan biologique.")
        if p.stage != "lab_proposed":
            return pathway_dict(p)
        items = json.loads(p.labs_json or "[]")
        if codes is not None:
            wanted = {c.upper() for c in codes if c.upper() in labs.CATALOG}
            for it in items:
                it["selected"] = it["code"] in wanted
            for c in sorted(wanted - {it["code"] for it in items}):
                items.append({"code": c, "label": labs.label(c), "motif": "", "justification": "Ajouté par le médecin.", "selected": True, "source": "médecin"})
        p.labs_json = json.dumps(items, ensure_ascii=False)
        p.stage, p.labs_validated_by, p.labs_validated_at = "lab_ordered", by, now
        p.results_due_at = now + timedelta(seconds=settings.fever_lab_delay_s)
        p.updated_at = now
        s.flush()
        d = pathway_dict(p)
    hold_rooms.discard(d["room"])
    return d


def set_comfort_note(pid: int, note: str) -> dict[str, Any]:
    with session_scope() as s:
        p = s.get(FeverPathway, pid)
        p.comfort_note = note[:600]
        p.updated_at = datetime.now(timezone.utc)
        s.flush()
        return pathway_dict(p)
