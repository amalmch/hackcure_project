"""Démarrage et registre des 6 agents."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from ..config import settings
from .ambulance import AmbulanceAgent
from .base import Agent
from .care import DiagnosticsAgent, InterventionAgent, MedicationAgent
from .environment import EnvironmentAgent
from .fever import FeverAgent
from .prediction import PredictionAgent
from .psych import PsychAgent
from .followup import FollowUpAgent
from .report import ReportAgent
from .risk import RiskAgent
from .vision import VisionAgent
from .vitals import VitalsAgent

logger = logging.getLogger("hackcure.agents")

agents: dict[str, Agent] = {}
AGENT_CLASSES: list[type[Agent]] = [VisionAgent, VitalsAgent, EnvironmentAgent, RiskAgent, FollowUpAgent, ReportAgent, FeverAgent, DiagnosticsAgent, MedicationAgent, InterventionAgent, PsychAgent, PredictionAgent, AmbulanceAgent]


async def start() -> list[asyncio.Task]:
    if not settings.agents_enabled:
        logger.info("Agents désactivés (AGENTS_ENABLED=0)")
        return []
    tasks = []
    for cls in AGENT_CLASSES:
        a = cls()
        agents[a.name] = a
        tasks.append(a.start())
    logger.info("Agents démarrés : %s", ", ".join(agents))
    # préchauffage du client LLM (import du SDK dans un thread) pour que la première alerte ne paie pas ce coût
    from .llm import AnthropicLlm, get_llm

    llm = get_llm()
    if isinstance(llm, AnthropicLlm):
        tasks.append(asyncio.create_task(llm.ensure_client(), name="llm-prewarm"))
    return tasks


def get(name: str) -> Optional[Agent]:
    return agents.get(name)


def report_agent() -> ReportAgent:
    a = agents.get("ReportAgent")
    if a is None:
        a = ReportAgent()  # utilisable même si les agents sont désactivés
        agents[a.name] = a
    return a  # type: ignore[return-value]


def infos() -> list[dict[str, Any]]:
    return [a.info() for a in agents.values()]
