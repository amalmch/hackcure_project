"""
Correspondance classes CV → contrat `vision/state` (section 6.1 du PROMPT).

| Classe CV                                   | posture        | activity                         | zone         |
| patient_lying (dans le polygone du lit)     | lying_bed      | awake_bed / sleeping (> 5 min)   | bed          |
| patient_sitting                             | sitting_bed / sitting_chair | awake_bed / out_of_bed | bed / floor |
| patient_moving_out, patient_near_fall       | standing       | out_of_bed                       | floor        |
| patient_out / aucune détection              | absent         | out_of_room (toilet si dernière zone = bathroom_door) | exit / none |
| patient_fallen confirmé (FallDetector)      | on_floor       | fall                             | floor        |
| falling (modèle 2 classes)                  | on_floor       | fall                             | floor        |
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

POSTURES = ("lying_bed", "sitting_bed", "sitting_chair", "standing", "walking", "on_floor", "absent")
ACTIVITIES = ("sleeping", "awake_bed", "out_of_bed", "toilet", "out_of_room", "fall")
ZONES = ("bed", "floor", "bathroom_door", "exit", "none")


@dataclass
class ContractState:
    posture: str
    activity: str
    zone: str

    def as_tuple(self) -> tuple[str, str, str]:
        return self.posture, self.activity, self.zone


def map_to_contract(
    cv_class: Optional[str],
    zone: str,
    fall_confirmed: bool = False,
    still_seconds: float = 0.0,
    last_zone: str = "none",
    moving: bool = False,
    sleeping_after_s: float = 300.0,
) -> ContractState:
    """
    Args:
        cv_class: classe canonique (`patient_*`), `falling` / `no_falling` (2 classes), classe pose
                  (`pose_lying`, `pose_sitting`, `pose_standing`) ou None (aucune détection).
        zone: zone courante (après hystérésis) du point de test.
        fall_confirmed: chute confirmée par `FallDetector` (classes canoniques) — `falling` est acceptée directement.
        still_seconds: durée d'immobilité (pour `sleeping`).
        last_zone: dernière zone connue avant disparition (toilettes si `bathroom_door`).
        moving: déplacement notable (pour `walking`).
    """
    c = (cv_class or "").lower()
    in_bed = zone == "bed"

    if c == "falling" or (c == "patient_fallen" and fall_confirmed):
        return ContractState("on_floor", "fall", "floor")
    if c == "patient_fallen":  # pas encore confirmé : quasi-chute, on reste prudent
        return ContractState("standing", "out_of_bed", "floor")
    if c in ("patient_out", "") or zone == "exit":
        activity = "toilet" if last_zone == "bathroom_door" or zone == "bathroom_door" else "out_of_room"
        return ContractState("absent", activity, "exit" if c == "patient_out" or zone == "exit" else "none")
    if c in ("patient_lying", "pose_lying", "no_falling"):
        if in_bed or c == "no_falling" and zone in ("bed", "none"):
            return ContractState("lying_bed", "sleeping" if still_seconds >= sleeping_after_s else "awake_bed", "bed")
        if c == "no_falling":
            return ContractState("standing" if not moving else "walking", "out_of_bed", "floor" if zone != "bathroom_door" else "bathroom_door")
        return ContractState("on_floor" if fall_confirmed else "lying_bed", "fall" if fall_confirmed else "awake_bed", "floor" if fall_confirmed else "bed")
    if c in ("patient_sitting", "pose_sitting"):
        if in_bed:
            return ContractState("sitting_bed", "awake_bed", "bed")
        return ContractState("sitting_chair", "out_of_bed", "floor")
    if c in ("patient_moving_out", "patient_near_fall", "pose_standing"):
        posture = "walking" if moving else "standing"
        return ContractState(posture, "out_of_bed", "bathroom_door" if zone == "bathroom_door" else "floor")
    if c == "possible_discomfort":
        return ContractState("lying_bed" if in_bed else "sitting_chair", "awake_bed" if in_bed else "out_of_bed", "bed" if in_bed else "floor")
    # classe inconnue : on se fie à la zone
    if in_bed:
        return ContractState("lying_bed", "awake_bed", "bed")
    return ContractState("standing", "out_of_bed", "floor")


def pose_rule_posture(keypoints: dict[str, tuple[float, float]], box_h: float) -> str:
    """
    Posture par règles à partir des points clés COCO (modèle pose pré-entraîné, repli 6.4) :
    angle du torse (épaules → hanches) et hauteur des hanches dans la boîte.
    Renvoie `pose_lying | pose_sitting | pose_standing`.
    """
    import math

    def mid(a: str, b: str) -> Optional[tuple[float, float]]:
        pa, pb = keypoints.get(a), keypoints.get(b)
        if not pa or not pb:
            return pa or pb
        return ((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2)

    sh, hp = mid("left_shoulder", "right_shoulder"), mid("left_hip", "right_hip")
    kn = mid("left_knee", "right_knee")
    if not sh or not hp:
        return "pose_standing"
    dx, dy = hp[0] - sh[0], hp[1] - sh[1]
    torso_angle = abs(math.degrees(math.atan2(dx, dy if dy != 0 else 1e-6)))  # 0 = vertical, 90 = horizontal
    if torso_angle > 55:
        return "pose_lying"
    if kn and box_h > 0:
        hip_to_knee = abs(kn[1] - hp[1]) / box_h
        if hip_to_knee < 0.18:
            return "pose_sitting"
    return "pose_standing"
