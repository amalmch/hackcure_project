"""
Intervention Agent Adapter Contract
====================================
Interface defining the contract between HackCure Monitoring AI and
the Teammate Intervention Agent service.
"""

from __future__ import annotations
import json
import logging
import os
from typing import Dict, List, Optional

logger = logging.getLogger("hackcure.agent_adapter")


class InterventionAgentAdapter:
    """
    Adapter bridging the HackCure Monitoring AI with Teammate Intervention Agents.
    Acts as a resilient client that falls back gracefully if the agent service is offline.
    """
    def __init__(self, agent_service_url: Optional[str] = None):
        # Hospital Copilot : le service d'intervention est la plateforme elle-même (VisionAgent → RiskAgent).
        # Un service externe reste possible par INTERVENTION_AGENT_URL ; sans URL, aucune requête n'est faite.
        self.agent_service_url = agent_service_url or os.environ.get("INTERVENTION_AGENT_URL") or None

    def request_recommendation(self, ai_event: dict) -> List[str]:
        """
        Sends structured AI event to the intervention agent service.
        Returns recommendations list.
        """
        # 1. Attempt live HTTP call to teammate's agent service
        try:
            if self.agent_service_url:
                import requests

                resp = requests.post(self.agent_service_url, json=ai_event, timeout=1.0)
                if resp.status_code == 200:
                    data = resp.json()
                    if "recommendations" in data:
                        return data["recommendations"]
        except Exception:
            # Safe monitoring fallback: teammate agent service not yet running
            pass

        # 2. Local Clinical Decision Support Fallback
        recommendations = []
        risk_level = ai_event.get("risk_level", "low")
        evidence = ai_event.get("evidence", []) or ai_event.get("behavior_indicators", [])
        event_type = ai_event.get("event_type", "normal")

        if risk_level == "critical" or event_type in ("fall", "fall_and_pain"):
            recommendations.append("EMERGENCY: Immediate clinical intervention required — patient fallen.")
            recommendations.append("PROTOCOL: Follow hospital emergency escalation and check vitals.")
        elif risk_level == "high":
            if "instability_pattern" in evidence or "sudden_downward_motion" in evidence:
                recommendations.append("PREVENTIVE ALERT: Patient exhibits severe postural instability. Dispatch nurse for fall prevention.")
            elif event_type == "pain" or "possible_discomfort" in evidence:
                recommendations.append("CARE ALERT: Visible patient discomfort detected. Nursing assessment requested.")
            else:
                recommendations.append("WARNING: High behavioral risk detected. Human verification required.")
        elif risk_level == "moderate":
            if "prolonged_immobility" in evidence:
                recommendations.append("INFO: Patient immobile for extended window. Schedule routine position change.")
            elif "agitation_detected" in evidence:
                recommendations.append("OBSERVATION: Unusual patient agitation observed. Check patient comfort.")
            elif "possible_discomfort" in evidence:
                recommendations.append("OBSERVATION: Mild discomfort indicators observed. Monitor closely.")
            else:
                recommendations.append("INFO: Unusual activity pattern detected. Periodic monitoring recommended.")

        # Equipment Domain Handling
        if ai_event.get("entity_type") == "machine":
            recommendations.append("BIOMEDICAL: Dispatch maintenance technician for visual equipment inspection.")

        return recommendations


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    adapter = InterventionAgentAdapter()
    test_event = {
        "event_id": "evt_test123",
        "entity_type": "patient",
        "entity_id": "patient_01",
        "risk_level": "high",
        "evidence": ["instability_pattern"],
    }
    recs = adapter.request_recommendation(test_event)
    logger.info(f"Generated recommendations: {recs}")
