"""
Accès LLM : `MockLlm` (hors-ligne, déterministe) ou `AnthropicLlm` (SDK anthropic, modèle configurable).
Sorties JSON validées par l'appelant ; en cas d'erreur / délai dépassé → None → plan de secours.
Prompts en français dans `app/prompts/*.md` (aide à la décision, ne jamais inventer de valeur).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

from ..config import settings

logger = logging.getLogger("hackcure.llm")
PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def load_prompt(name: str, **vars: Any) -> str:
    path = PROMPTS_DIR / f"{name}.md"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    for k, v in vars.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


def extract_json(text: str) -> Optional[dict[str, Any]]:
    """Premier objet JSON équilibré trouvé dans le texte (bloc ```json``` ou accolades)."""
    if not text:
        return None
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if m:
        try:
            data = json.loads(m.group(1))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    decoder = json.JSONDecoder()
    pos = text.find("{")
    while pos >= 0:
        try:
            data, _end = decoder.raw_decode(text, pos)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
        pos = text.find("{", pos + 1)
    return None


class BaseLlm:
    name = "base"

    async def complete_text(self, system: str, user: str, max_tokens: int = 1400) -> Optional[str]:  # pragma: no cover
        raise NotImplementedError

    async def complete_json(self, system: str, user: str, max_tokens: int = 1400) -> Optional[dict[str, Any]]:
        from .. import privacy

        # V3 : rien de nominatif ne part vers le LLM (pseudonyme, âge, sexe, données cliniques seulement)
        system, user = privacy.outbound("llm", system), privacy.outbound("llm", user)
        try:
            text = await asyncio.wait_for(self.complete_text(system, user, max_tokens), timeout=settings.llm_timeout_s)
        except asyncio.TimeoutError:
            logger.warning("LLM %s : délai dépassé (%.0fs)", self.name, settings.llm_timeout_s)
            return None
        except Exception as exc:
            logger.warning("LLM %s : erreur %s", self.name, exc.__class__.__name__)
            return None
        data = extract_json(text or "")
        if data is None:
            logger.warning("LLM %s : reponse non analysable (JSON absent ou tronque, %d caracteres) -> plan de secours", self.name, len(text or ""))
        return data


class MockLlm(BaseLlm):
    """Rédaction hors-ligne : réponses structurées à partir du contexte fourni (sans inventer de valeurs)."""

    name = "mock"

    async def complete_text(self, system: str, user: str, max_tokens: int = 1400) -> Optional[str]:
        ctx = extract_json(user) or {}
        task = ctx.get("task", "")
        if task == "risk_plan":
            return json.dumps(self._risk_plan(ctx), ensure_ascii=False)
        if task == "shift_report":
            return json.dumps({"markdown": self._shift_report(ctx)}, ensure_ascii=False)
        if task == "medical_report":
            return json.dumps({"content": self._medical_report(ctx)}, ensure_ascii=False)
        return json.dumps({"text": "Réponse simulée (LLM_PROVIDER=mock)."}, ensure_ascii=False)

    # ── rédactions simulées ─────────────────────────────────────────────────
    @staticmethod
    def _fmt_vitals(v: dict[str, Any]) -> str:
        parts = []
        if v.get("hr") is not None:
            parts.append(f"FC {round(v['hr'])} bpm")
        if v.get("spo2") is not None:
            parts.append(f"SpO2 {round(v['spo2'])} %")
        if v.get("sys") is not None and v.get("dia") is not None:
            parts.append(f"PA {round(v['sys'])}/{round(v['dia'])} mmHg")
        if v.get("tempC") is not None:
            parts.append(f"T° {float(v['tempC']):.1f} °C")
        if v.get("rr") is not None:
            parts.append(f"FR {round(v['rr'])}/min")
        return ", ".join(parts) if parts else "constantes non disponibles"

    def _risk_plan(self, ctx: dict[str, Any]) -> dict[str, Any]:
        from .plans import FALLBACK_PLANS, TYPE_LABELS

        rtype = ctx.get("risk_type", "")
        sev = ctx.get("severity", "medium")
        p = ctx.get("patient") or {}
        v = ctx.get("vitals") or {}
        details = ctx.get("details") or {}
        name = p.get("full_name") or p.get("display_name") or "le patient"
        allergies = p.get("allergies") or "aucune connue"
        label = TYPE_LABELS.get(rtype, rtype)
        news = ctx.get("news2")
        expl = [f"{label} détecté(e) en chambre {ctx.get('room')} pour {name} ({p.get('age', '?')} ans, risque de chute {p.get('fall_risk', '?')})."]
        expl.append(f"Dernières constantes : {self._fmt_vitals(v)}.")
        if news is not None:
            expl.append(f"NEWS2 = {news}.")
        if details:
            expl.append("Éléments observés : " + ", ".join(f"{k} = {val}" for k, val in details.items() if val is not None) + ".")
        if p.get("history"):
            expl.append(f"Antécédents à considérer : {p['history']}.")
        expl.append(f"Allergies : {allergies}. Traitements en cours : {ctx.get('treatments') or 'aucun'}.")
        expl.append(f"Sévérité retenue (règles déterministes) : {sev}. Cette analyse est une aide à la décision ; un soignant valide chaque étape.")
        steps = [dict(s) for s in FALLBACK_PLANS.get(rtype, FALLBACK_PLANS["default"])]
        if "aucune" not in allergies.lower():
            steps.insert(min(2, len(steps)), {"text": f"Vérifier les allergies ({allergies}) avant toute administration médicamenteuse."})
        return {"explanation": " ".join(expl), "steps": steps[:6], "severity_ok": True}

    def _shift_report(self, ctx: dict[str, Any]) -> str:
        lines = [f"# Rapport de garde — {ctx.get('period', '')}", "", f"_Généré par ReportAgent ({self.name}) — aide à la décision, à valider par l'infirmier(ère) responsable._", ""]
        for room in ctx.get("rooms", []):
            lines.append(f"## Chambre {room.get('room')} — {room.get('patient') or 'libre'}")
            if room.get("patient"):
                lines.append(f"- **État actuel** : posture {room.get('posture')}, activité {room.get('activity')}, expression {room.get('expression')}.")
                lines.append(f"- **Constantes** : {self._fmt_vitals(room.get('vitals') or {})}.")
                lines.append(f"- **Humeur observée** : {room.get('mood') or 'non évaluée'}.")
                risks = room.get("risks") or []
                lines.append(f"- **Risques** ({len(risks)}) : " + ("; ".join(f"{r['title']} [{r['severity']}, {r['status']}]" for r in risks) if risks else "aucun."))
                actions = room.get("actions") or []
                if actions:
                    lines.append("- **Actions réalisées** : " + "; ".join(actions) + ".")
                events = room.get("events") or []
                if events:
                    lines.append("- **Événements** : " + "; ".join(events[:8]) + ("…" if len(events) > 8 else "") + ".")
            lines.append("")
        lines.append("## Points d'attention pour la relève")
        attn = [f"Chambre {r.get('room')} : {x['title']} ({x['status']})" for r in ctx.get("rooms", []) for x in (r.get("risks") or []) if x["status"] != "resolved"]
        lines += [f"- {a}" for a in attn] or ["- Aucun risque ouvert."]
        return "\n".join(lines)

    def _medical_report(self, ctx: dict[str, Any]) -> str:
        p = ctx.get("patient") or {}
        a = ctx.get("admission") or {}
        v = ctx.get("vitals") or {}
        risks = ctx.get("risks") or []
        return "\n".join([
            f"COMPTE RENDU MÉDICAL (brouillon IA — {self.name})",
            "",
            f"Patient : {p.get('full_name')} ({p.get('code')}), {p.get('age')} ans, groupe {p.get('blood_group')}, allergies : {p.get('allergies') or 'aucune connue'}.",
            f"Admission du {a.get('admitted_at', '')} en chambre {a.get('room_code')} — motif : {a.get('reason')}. Médecin référent : {a.get('referring_doctor')}.",
            "",
            f"Antécédents : {p.get('history') or 'non renseignés'}.",
            f"Traitements en cours : {ctx.get('treatments') or 'aucun'}.",
            "",
            f"Constantes récentes : {self._fmt_vitals(v)}" + (f" ; NEWS2 {ctx.get('news2')}" if ctx.get("news2") is not None else "") + ".",
            "Événements du séjour : " + ("; ".join(f"{r['title']} ({r['severity']}, {r['status']})" for r in risks) if risks else "aucun événement notable") + ".",
            "",
            "Évolution : à compléter par le médecin.",
            "Conclusion / conduite à tenir : à compléter par le médecin.",
            "",
            "Ce brouillon ne contient que des valeurs mesurées ou saisies ; il doit être relu et signé par un médecin.",
        ])


class AnthropicLlm(BaseLlm):
    """Le SDK (import lourd) est chargé dans un thread à la première utilisation pour ne jamais bloquer la boucle asyncio."""

    name = "anthropic"

    def __init__(self) -> None:
        self.client = None
        self.model = settings.llm_model
        self._lock = asyncio.Lock()

    def _build_client(self):
        import anthropic

        return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def ensure_client(self) -> None:
        if self.client is None:
            async with self._lock:
                if self.client is None:
                    self.client = await asyncio.to_thread(self._build_client)
                    logger.info("Client Anthropic prêt (%s)", self.model)

    async def complete_text(self, system: str, user: str, max_tokens: int = 1400) -> Optional[str]:
        await self.ensure_client()
        resp = await self.client.messages.create(
            model=self.model, max_tokens=max(max_tokens, 8000), system=system,  # le modèle consomme des tokens de réflexion avant de répondre
            messages=[{"role": "user", "content": user}],
        )
        return "".join(getattr(b, "text", "") for b in resp.content)


FALLBACK_LABEL = "réponse de secours (LLM indisponible)"
health: dict[str, Any] = {"status": "n/a", "detail": None, "checked_at": None}


async def check_health() -> dict[str, Any]:
    """Appel minimal pour vérifier la clé (`/health` → llm: ok | error | mock)."""
    import time as _time

    llm = get_llm()
    if not isinstance(llm, AnthropicLlm):
        health.update(status="mock", detail="LLM_PROVIDER=mock (ou clé absente)", checked_at=_time.time())
        return health
    try:
        await llm.ensure_client()
        await asyncio.wait_for(llm.client.messages.create(model=llm.model, max_tokens=5, messages=[{"role": "user", "content": "ping"}]), timeout=30)
        health.update(status="ok", detail=f"{llm.model} répond", checked_at=_time.time())
    except Exception as exc:
        health.update(status="error", detail=f"{exc.__class__.__name__}: {str(exc)[:160]}", checked_at=_time.time())
        logger.warning("Vérification LLM : %s", health["detail"])
    return health


async def start_health_check() -> list[asyncio.Task]:
    return [asyncio.create_task(check_health(), name="llm-health")]


_llm: Optional[BaseLlm] = None


def get_llm() -> BaseLlm:
    global _llm
    if _llm is None:
        if settings.llm_provider == "anthropic" and settings.anthropic_api_key:
            _llm = AnthropicLlm()
            logger.info("LLM Anthropic (%s) — client chargé en arrière-plan", settings.llm_model)
        else:
            _llm = MockLlm()
    return _llm
