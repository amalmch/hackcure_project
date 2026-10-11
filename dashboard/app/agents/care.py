"""
Agents de soins de la V2 (étape 4).

- **DiagnosticsAgent** : hypothèses diagnostiques mises à jour en continu (règles déterministes de
  `clinical/diagnostics.py`), synthèse rédigée par le LLM (workflow n8n `diagnostics-live`).
- **MedicationAgent** : plan d'administration — rappel à l'heure de chaque prise, relance après 30 min de
  retard, médecin prévenu après 60 min, prises conditionnelles (« si fièvre > 38,5 °C ») déclenchées par
  les constantes ; workflow n8n `medication-reminders`.
- **InterventionAgent** : chaque risque résolu et vérifié produit un brouillon de compte rendu d'intervention
  (workflow n8n `intervention-report`), à valider et signer par le soignant, rangé dans le dossier médical.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlmodel import select

from .. import care, orchestration
from ..bus import Event, bus
from ..clinical.diagnostics import hypotheses
from ..config import settings
from ..db import session_scope
from ..ingest import handler
from ..models import (ActionPlan, ActionStep, AgentLog, CareMessage, DiagnosticHypothesis, MedicalRecordEntry, MedicationDose, Patient, Risk, StaffVisit, TreatmentOrder, TreatmentOrderLine)
from ..notify import notify
from ..ws import manager
from .base import Agent

esc = lambda t: str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
_pending_messages: dict[str, str] = {}  # référence du rappel → message Telegram (composé par la plateforme, jamais par le LLM)


# ═════════════════════════════════════════════════════════════════════════════
class DiagnosticsAgent(Agent):
    name = "DiagnosticsAgent"
    description = "Tient à jour les hypothèses diagnostiques de chaque patient (constantes, scores, vision, biologie, dossier) : éléments pour, contre, examens utiles."
    patterns = ["internal/reset"]

    def __init__(self) -> None:
        super().__init__()
        self.tick_interval = settings.diagnostics_tick_s
        self.signature: dict[str, str] = {}
        self.last_llm: dict[str, float] = {}

    async def handle(self, ev: Event) -> None:
        self.signature.clear()

    async def on_tick(self) -> None:
        for room in handler.ROOMS:
            await self.evaluate(room)

    async def evaluate(self, room: str) -> None:
        changed, payload, context, pid = False, None, None, None
        with session_scope() as s:
            ctx = care.clinical_context(s, room)
            if not ctx or not ctx["patient_pk"]:
                return
            hyps = hypotheses(ctx)
            sig = "|".join(f"{h['code']}:{h['probability']}" for h in hyps)
            if self.signature.get(room) == sig:
                return
            self.signature[room] = sig
            now = datetime.now(timezone.utc)
            existing = {h.code: h for h in s.exec(select(DiagnosticHypothesis).where(DiagnosticHypothesis.patient_pk == ctx["patient_pk"], DiagnosticHypothesis.admission_id == ctx["admission_id"])).all()}
            for h in hyps:
                row = existing.pop(h["code"], None)
                if row is None:
                    row = DiagnosticHypothesis(patient_pk=ctx["patient_pk"], admission_id=ctx["admission_id"], room_code=room, code=h["code"])
                    s.add(row)
                row.label, row.score, row.probability = h["label"], h["score"], h["probability"]
                row.pros_json, row.cons_json, row.exams_json = (json.dumps(h[k], ensure_ascii=False) for k in ("pros", "cons", "exams"))
                if row.status == "inactive":
                    row.status = "active"
                row.updated_at = now
            for row in existing.values():  # plus d'élément en faveur : l'hypothèse non tranchée devient inactive
                if row.status == "active":
                    row.status, row.updated_at = "inactive", now
            s.flush()
            rows = s.exec(select(DiagnosticHypothesis).where(DiagnosticHypothesis.patient_pk == ctx["patient_pk"], DiagnosticHypothesis.admission_id == ctx["admission_id"], DiagnosticHypothesis.status != "inactive")
                          .order_by(DiagnosticHypothesis.score.desc())).all()
            payload = [care.hypothesis_out(r) for r in rows]
            pid, changed = ctx["patient_id"], True
            top = [h for h in hyps if h["probability"] != "faible"]
            if top and time.time() - self.last_llm.get(room, 0) > 120:
                self.last_llm[room] = time.time()
                context = {"task": "diagnostics_live", "chambre": room, "patient": {"nom": ctx["name"], "age": ctx["age"], "antecedents": ctx["history"], "allergies": ctx["allergies"] or "aucune connue"},
                           "traitements_en_cours": ctx["treatments"], "motif_hospitalisation": ctx["admission_reason"], "constantes": ctx["vitals"], "news2": ctx["news2"], "qsofa": ctx["qsofa"],
                           "vision": {"posture": ctx["posture"], "expression": ctx["expression"]}, "biologie_recente": ctx["labs"], "risques_ouverts": ctx["open_risks"],
                           "hypotheses": [{k: h[k] for k in ("label", "probability", "pros", "cons", "exams")} for h in hyps]}
        if not changed:
            return
        await manager.broadcast({"type": "diagnostics", "room": room, "patient_id": pid, "hypotheses": payload})
        lead = payload[0] if payload else None
        await self.log(room, input=f"réévaluation des hypothèses ({len(payload)} actives)", reasoning="Règles déterministes sur constantes, NEWS2, qSOFA, vision, biologie récente et dossier. Probabilités qualitatives ; le médecin confirme ou rejette.",
                       output=(f"{lead['label']} : probabilité {lead['probability']}" if lead else "aucune hypothèse au-dessus du seuil"))
        if context:
            await orchestration.ask("diagnostics-live", pid, context, room=room)


@orchestration.handler("diagnostics-live")
async def on_diagnostics_summary(ref: str, result: dict[str, Any], meta: dict[str, Any]) -> Optional[str]:
    with session_scope() as s:
        p = s.exec(select(Patient).where(Patient.patient_id == ref)).first()
        if not p:
            return None
        body = str(result.get("summary") or "").strip()[:1500]
        nxt = [str(x)[:200] for x in (result.get("next_steps") or [])][:5]
        if nxt:
            body += "\n" + "\n".join(f"• {x}" for x in nxt)
        msg = CareMessage(patient_pk=p.id, room_code=meta.get("room") or "", author="DiagnosticsAgent", author_name=meta.get("provider") or "IA", role="ai", kind="ai", body=body)
        s.add(msg)
        s.flush()
        out = message_out(msg)
    await manager.broadcast({"type": "care_message", "patient_id": ref, "message": out})
    return None


def message_out(m: CareMessage) -> dict[str, Any]:
    return {"id": m.id, "author": m.author, "author_name": m.author_name, "role": m.role, "kind": m.kind, "body": m.body, "mentions": [x for x in m.mentions.split(",") if x],
            "hypothesis_id": m.hypothesis_id, "created_at": care.aware(m.created_at).isoformat()}


# ═════════════════════════════════════════════════════════════════════════════
class MedicationAgent(Agent):
    name = "MedicationAgent"
    description = "Suit le plan d'administration : rappel à l'heure de la prise, relance après 30 min de retard, médecin prévenu après 60 min ; déclenche les prises conditionnelles."
    patterns = ["internal/reset"]
    tick_interval = 3.0

    async def handle(self, ev: Event) -> None:
        return

    async def on_tick(self) -> None:
        now = datetime.now(timezone.utc)
        reminders: list[dict[str, Any]] = []
        with session_scope() as s:
            self._conditional(s, now)
            horizon = now + timedelta(seconds=5)
            for d in s.exec(select(MedicationDose).where(MedicationDose.status == "scheduled", MedicationDose.due_at <= horizon)).all():
                order = s.get(TreatmentOrder, d.order_id)
                if not order or order.status != "active":
                    continue
                late = (now - care.aware(d.due_at)).total_seconds()
                kind = None
                if d.reminded_at is None:
                    d.reminded_at, kind = now, "reminder"
                elif late >= settings.med_escalate_s and d.escalated_at is None:
                    d.escalated_at, kind = now, "escalation"
                elif late >= settings.med_relaunch_s and d.relaunched_at is None:
                    d.relaunched_at, kind = now, "relaunch"
                if kind:
                    s.flush()
                    reminders.append({"kind": kind, "dose": care.dose_out(s, d, now), "late_min": int(late // 60), "late_s": int(late)})
        for r in reminders:
            await self.send(r)

    def _conditional(self, s, now: datetime) -> None:
        """Prises « si … » : créées quand la condition est remplie et que l'intervalle minimal est respecté."""
        for ln, order in s.exec(select(TreatmentOrderLine, TreatmentOrder).join(TreatmentOrder, TreatmentOrder.id == TreatmentOrderLine.order_id)
                                .where(TreatmentOrder.status == "active", TreatmentOrderLine.prn.is_(True))).all():
            if not ln.condition_metric or ln.condition_value is None:
                continue
            value = (handler.room_state(order.room_code).get("vitals") or {}).get(ln.condition_metric)
            if value is None:
                continue
            met = {">": value > ln.condition_value, ">=": value >= ln.condition_value, "<": value < ln.condition_value, "<=": value <= ln.condition_value}.get(ln.condition_op, False)
            if not met:
                continue
            last = s.exec(select(MedicationDose).where(MedicationDose.line_id == ln.id).order_by(MedicationDose.due_at.desc())).first()
            if last and (last.status == "scheduled" or (now - care.aware(last.due_at)).total_seconds() < ln.min_interval_h * 3600):
                continue
            s.add(MedicationDose(line_id=ln.id, order_id=order.id, admission_id=order.admission_id, patient_pk=order.patient_pk, room_code=order.room_code, medication_id=ln.medication_id,
                                 label=f"{ln.dci} {ln.dose} {ln.route}".strip(), due_at=now, conditional=True, note=f"condition remplie : {care.condition_text(ln)} (mesuré : {value:g})"))
        s.flush()

    async def send(self, r: dict[str, Any]) -> None:
        d, kind = r["dose"], r["kind"]
        room, when = d["room"], datetime.fromisoformat(d["due_at"]).astimezone().strftime("%H:%M")
        allergy = f" ⚠ {d['allergy_alert']}" if d["allergy_alert"] else ""
        cond = f" ({d['note']})" if d["conditional"] and d["note"] else ""
        if kind == "reminder":
            title, body, level, role = f"💊 Prise à administrer — chambre {room}", f"{d['patient_name']} : {d['label']}, prévue à {when}{cond}.{allergy}", "info", "nurse"
            tg = f"💊 <b>Prise à administrer — chambre {esc(room)}</b>\n{esc(d['patient_name'])} : <b>{esc(d['label'])}</b>, prévue à {when}{esc(cond)}.{esc(allergy)}\nPlan de soins → « Administré »."
        elif kind == "relaunch":
            title, body, level, role = f"⏰ Prise en retard — chambre {room}", f"{d['patient_name']} : {d['label']} prévue à {when}, non administrée depuis {r['late_min']} min. Relance.{allergy}", "warning", "nurse"
            tg = f"⏰ <b>RELANCE — prise en retard, chambre {esc(room)}</b>\n{esc(d['patient_name'])} : <b>{esc(d['label'])}</b> prévue à {when}, retard {r['late_min']} min."
        else:
            title, body, level, role = f"⬆️ Prise non administrée — chambre {room}", f"{d['patient_name']} : {d['label']} prévue à {when}, toujours non administrée après {r['late_min']} min. Médecin de garde prévenu.", "warning", "duty_doctor"
            tg = f"⬆️ <b>MÉDECIN DE GARDE — prise non administrée, chambre {esc(room)}</b>\n{esc(d['patient_name'])} : <b>{esc(d['label'])}</b> prévue à {when}, retard {r['late_min']} min."
        await notify(level, title, body, room=room, target_role=role, telegram=False)
        await manager.broadcast({"type": "care_plan", "event": kind, "dose": d})
        if kind == "relaunch":  # le retard devient un risque suivi par la boucle soignant (résolu par l'administration enregistrée)
            await bus.publish("internal/risk_candidate", {"room": room, "type": "medication_late", "source_agent": self.name, "details": {"dose": d["label"], "dueAt": when, "lateMin": r["late_min"]}})
        context = {"task": "medication_reminder", "type_de_rappel": {"reminder": "prise due", "relaunch": "relance (retard > 30 min)", "escalation": "médecin prévenu (retard > 60 min)"}[kind],
                   "chambre": room, "patient": d["patient_name"], "allergies": d["allergies"] or "aucune connue", "prise": d["label"], "heure_prevue": when, "retard_min": r["late_min"],
                   "condition": d["condition"] or None, "alerte_allergie": d["allergy_alert"] or None}
        _pending_messages[f"{d['id']}:{kind}"] = tg
        path = await orchestration.ask("medication-reminders", f"{d['id']}:{kind}", context, room=room)
        await self.log(room, input=f"prise #{d['id']} {d['label']} prévue à {when} — {kind}", reasoning={"reminder": "Heure de la prise : rappel à l'infirmier.", "relaunch": f"Retard > {settings.med_relaunch_s / 60:.0f} min : relance et risque « prise en retard ».",
                       "escalation": f"Retard > {settings.med_escalate_s / 60:.0f} min : médecin de garde prévenu."}[kind] + (" Notification orchestrée par n8n (medication-reminders)." if path == "n8n" else " Notification locale."),
                       output=title, status="ok" if kind == "reminder" else "error")


@orchestration.handler("medication-reminders")
async def on_medication_note(ref: str, result: dict[str, Any], meta: dict[str, Any]) -> Optional[str]:
    """Le LLM ajoute au rappel un point de vigilance (allergie, interaction, surveillance) ; le message part sur Telegram."""
    note = str(result.get("vigilance") or "").strip()[:300]
    base = _pending_messages.pop(ref, "")
    if not base:
        return None
    return base + (f"\n<i>Vigilance : {esc(note)}</i>" if note else "") + f"\n<i>{orchestration.DISCLAIMER}</i>"


# ═════════════════════════════════════════════════════════════════════════════
class InterventionAgent(Agent):
    name = "InterventionAgent"
    description = "Rédige le brouillon du compte rendu de chaque intervention (prise en charge d'un risque) à partir du journal des événements ; le soignant valide et signe, le document rejoint le dossier."
    patterns = ["internal/risk/resolved"]

    async def handle(self, ev: Event) -> None:
        await self.draft(int(ev.payload["risk_id"]), ev.payload.get("by") or "", ev.payload.get("detail") or "")

    async def draft(self, risk_id: int, by: str, detail: str) -> None:
        with session_scope() as s:
            risk = s.get(Risk, risk_id)
            if not risk or not risk.admission_id:
                return
            from ..models import Admission

            adm = s.get(Admission, risk.admission_id)
            p = s.get(Patient, adm.patient_id) if adm else None
            if not p or s.exec(select(MedicalRecordEntry).where(MedicalRecordEntry.patient_pk == p.id, MedicalRecordEntry.type == "intervention", MedicalRecordEntry.data_json.like(f'%"risk_id": {risk_id},%'))).first():
                return
            plan = s.exec(select(ActionPlan).where(ActionPlan.risk_id == risk_id).order_by(ActionPlan.id.desc())).first()
            steps = s.exec(select(ActionStep).where(ActionStep.plan_id == plan.id).order_by(ActionStep.order)).all() if plan else []
            visits = s.exec(select(StaffVisit).where(StaffVisit.room_code == risk.room_code, StaffVisit.started_at >= risk.detected_at).order_by(StaffVisit.started_at)).all()
            logs = s.exec(select(AgentLog).where(AgentLog.risk_id == risk_id).order_by(AgentLog.id)).all()
            iso = lambda d: care.aware(d).astimezone().strftime("%H:%M:%S") if d else None  # noqa: E731
            facts = {"risque": {"type": risk.type, "titre": risk.title, "severite": risk.severity, "detecte_a": iso(risk.detected_at), "pris_en_charge_a": iso(risk.acknowledged_at),
                                "escalade_a": iso(risk.escalated_at), "resolu_a": iso(risk.resolved_at), "verification": detail or risk.resolved_by, "source": risk.source_agent},
                     "plan_d_action": [{"etape": st.text, "faite": st.done, "par": st.done_by, "a": iso(st.done_at)} for st in steps],
                     "visites": [{"debut": iso(v.started_at), "fin": iso(v.ended_at), "personnes": v.persons} for v in visits],
                     "journal": [f"{iso(l.ts)} {l.agent} : {l.output[:160]}" for l in logs][-14:]}
            data = {"risk_id": risk_id, "room": risk.room_code, "facts": facts, "resolved_by": by}
            entry = MedicalRecordEntry(patient_pk=p.id, admission_id=adm.id, type="intervention", date=datetime.now(timezone.utc), title=f"Compte rendu d'intervention — {risk.title}", author="InterventionAgent (brouillon IA)",
                                       service="Clinique HackCure", facility="Clinique HackCure", summary="Brouillon en cours de rédaction…", content="", data_json=json.dumps(data, ensure_ascii=False, default=str), source="plateforme", status="draft")
            s.add(entry)
            s.flush()
            eid, room, title = entry.id, risk.room_code, risk.title
            context = {"task": "intervention_report", "chambre": room, "patient": {"nom": p.full_name, "age": p.age, "allergies": p.allergies or "aucune connue"}, **facts}
        path = await orchestration.ask("intervention-report", str(eid), context, room=room, risk_id=risk_id)
        await self.log(room, input=f"risque #{risk_id} « {title} » résolu et vérifié", reasoning="Brouillon de compte rendu d'intervention demandé " + ("au workflow n8n intervention-report" if path == "n8n" else "au LLM local")
                       + " à partir du journal (détection, plan, visites, vérification). À valider et signer par le soignant.", output=f"brouillon #{eid} dans le dossier médical", risk_id=risk_id)


@orchestration.handler("intervention-report")
async def on_intervention_report(ref: str, result: dict[str, Any], meta: dict[str, Any]) -> Optional[str]:
    with session_scope() as s:
        e = s.get(MedicalRecordEntry, int(ref))
        if not e or e.status != "draft":
            return None
        parts = []
        for title, key in (("Contexte", "context"), ("Intervention", "intervention"), ("Résultat", "outcome"), ("Suites à donner", "follow_up")):
            val = result.get(key)
            if isinstance(val, list):
                val = "\n".join(f"- {x}" for x in val)
            if val:
                parts += [f"## {title}", str(val).strip(), ""]
        e.content = "\n".join(parts).strip()
        e.summary = str(result.get("summary") or "")[:300] or "Brouillon de compte rendu d'intervention"
        e.author = f"InterventionAgent — brouillon IA ({meta.get('provider') or 'n8n'})"
        s.flush()
        p = s.get(Patient, e.patient_pk)
        out = {"id": e.id, "patient_id": p.patient_id if p else None, "title": e.title, "summary": e.summary, "status": e.status}
    await manager.broadcast({"type": "intervention_report", "event": "draft_ready", "report": out})
    await notify("info", "Compte rendu d'intervention à valider", f"{out['title']} — brouillon prêt, à relire et signer.", room=meta.get("room"), risk_id=meta.get("risk_id"), target_role="nurse", telegram=False)
    return None
