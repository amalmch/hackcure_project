"""
Analyse comportementale OPTIONNELLE (intégration des apports d'Amal 12e1eb2).

Assemble, pour l'edge et `dashboard/camera_loop.py` :
  - `temporal/risk_analyzer.TemporalRiskAnalyzer` (fenêtre glissante : immobilité, agitation, instabilité, inconfort) ;
  - `temporal/agent_adapter.InterventionAgentAdapter` (recommandations locales ; appel HTTP seulement si une URL est donnée) ;
  - `transformer/model.HackCurePatientTransformer` (DINOv2 + tête entraînée) — SEULEMENT si tout est déjà sur le disque.

Règle : on ne télécharge et on n'entraîne jamais rien ici. Si PyTorch, le backbone DINOv2 (cache torch hub) ou les
poids entraînés (`runs/patient_transformer/best_transformer.pt`) manquent, `load_transformer()` renvoie None et
l'analyse continue avec les seules sorties du détecteur (repli automatique, sans erreur).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from .temporal.agent_adapter import InterventionAgentAdapter
from .temporal.risk_analyzer import TemporalRiskAnalyzer

logger = logging.getLogger("hackcure.behavior")

CV_DIR = Path(__file__).resolve().parent.parent
TRANSFORMER_WEIGHTS = CV_DIR / "runs" / "patient_transformer" / "best_transformer.pt"
HUB_REPO = "facebookresearch_dinov2_main"
HUB_CHECKPOINT = "dinov2_vits14_pretrain.pth"
RESTING_STATES = {"patient_lying", "patient_sitting", "no_falling", "lying_bed", "sitting_bed", "sleeping"}


def transformer_status(weights: Path = TRANSFORMER_WEIGHTS) -> tuple[bool, str]:
    """(utilisable, raison). Ne touche pas au réseau."""
    if not Path(weights).exists():
        return False, f"poids entraînés absents ({weights.name})"
    try:
        import torch  # noqa: F401
        import torchvision  # noqa: F401
    except Exception as exc:
        return False, f"PyTorch / torchvision indisponible ({exc.__class__.__name__})"
    import torch

    hub = Path(torch.hub.get_dir())
    if not (hub / HUB_REPO).is_dir() or not (hub / "checkpoints" / HUB_CHECKPOINT).exists():
        return False, "backbone DINOv2 absent du cache torch hub (aucun téléchargement automatique)"
    return True, "ok"


def load_transformer(device: Optional[str] = None, weights: Path = TRANSFORMER_WEIGHTS) -> Any:
    """Transformer d'Amal prêt à l'emploi, ou None (repli). Charge le backbone depuis le cache local uniquement."""
    ok, why = transformer_status(weights)
    if not ok:
        logger.info("Vision Transformer non utilisé : %s → analyse comportementale sur le détecteur seul", why)
        return None
    try:
        import torch

        from .transformer.model import HackCurePatientTransformer

        local = str(Path(torch.hub.get_dir()) / HUB_REPO)
        original = torch.hub.load
        torch.hub.load = lambda repo, model, *a, **k: original(local, model, *a, source="local", **k)  # jamais de réseau
        try:
            model = HackCurePatientTransformer(device=device)
        finally:
            torch.hub.load = original
        ckpt = torch.load(weights, map_location=model.device, weights_only=True)
        model.head.load_state_dict(ckpt["model_state"])
        model.eval()
        logger.info("Vision Transformer chargé (%s)", weights)
        return model
    except Exception as exc:  # poids incompatibles, mémoire… : jamais bloquant
        logger.warning("Vision Transformer inutilisable (%s) → analyse comportementale sur le détecteur seul", exc)
        return None


class BehaviorAnalyzer:
    """Une observation par image traitée → événement de risque comportemental (contrat de l'analyseur d'Amal)."""

    def __init__(self, window_size: int = 30, device: Optional[str] = None, use_transformer: bool = True, agent_url: Optional[str] = None):
        self.analyzer = TemporalRiskAnalyzer(window_size=window_size)
        self.adapter = InterventionAgentAdapter(agent_service_url=agent_url)
        self.transformer = load_transformer(device) if use_transformer else None

    @property
    def mode(self) -> str:
        return "transformer" if self.transformer is not None else "temporal"

    def update(self, patient_id: str, cls_name: str, confidence: float, velocity: Optional[float] = None, crop_rgb: Any = None,
               discomfort: bool = False, discomfort_conf: float = 0.0, resting: Optional[bool] = None) -> dict[str, Any]:
        """`velocity` : déplacement du centre de la boîte entre deux images, rapporté à la diagonale de l'image.
        `resting` : patient au repos dans son lit (l'immobilité y est normale) ; déduit de la classe si None."""
        falling = cls_name in ("falling", "patient_fallen")
        fall_prob, posture, analysis = (0.9 if falling else 0.1), cls_name, None
        if self.transformer is not None and crop_rgb is not None and getattr(crop_rgb, "size", 0):
            try:
                analysis = self.transformer.predict_crop(crop_rgb)
                fall_prob, posture = float(analysis["fall_probability"]), analysis["class_name"]
            except Exception as exc:
                logger.debug("Transformer : %s", exc)
        self.analyzer.update_patient(patient_id=patient_id, yolo_state=cls_name, yolo_confidence=float(confidence), yolo_velocity=velocity,
                                     transformer_posture=posture, transformer_fall_prob=fall_prob, discomfort_detected=bool(discomfort), discomfort_conf=float(discomfort_conf))
        event = self.analyzer.generate_event(patient_id) or {}
        event["recommendations"] = self.adapter.request_recommendation(event) if event else []
        event["transformer_analysis"] = analysis
        event["transformer"] = self.transformer is not None
        # niveau strictement comportemental : la chute et la douleur ont déjà leurs propres signaux (posture, expression)
        level, score, evidence = event.get("risk_level", "low"), float(event.get("risk_score", 0.0)), list(event.get("evidence") or [])
        if event.get("event_type") != "behavioral_risk":
            level, score = "low", 0.1
        if resting is None:
            resting = cls_name in RESTING_STATES
        if resting and evidence == ["prolonged_immobility"]:  # un patient immobile dans son lit se repose : pas un risque
            level, score = "low", 0.1
        event["behavioral_level"], event["behavioral_score"] = level, round(score, 2)
        return event
