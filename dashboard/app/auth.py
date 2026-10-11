"""
Authentification JWT (cookie HttpOnly) et autorisations par rôle.

Rôles : pharmacist, receptionist, nurse, duty_doctor, general_doctor, owner.
Les permissions sont appliquées côté serveur par des dépendances FastAPI (`require("...")`)
et renvoyées au client (`/api/auth/me`) pour filtrer l'interface.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from pydantic import BaseModel

from .config import settings

logger = logging.getLogger("hackcure.auth")

ROLES = ("pharmacist", "receptionist", "nurse", "duty_doctor", "general_doctor", "owner", "psychiatrist")
DOCTORS = {"duty_doctor", "general_doctor", "owner"}
PSY = {"psychiatrist"}  # V2 : voit toute la plateforme, écrit le dossier médical et la psychologie
CLINICAL = {"receptionist", "nurse", "duty_doctor", "general_doctor", "owner", "psychiatrist"}  # tout sauf pharmacien
ALL = set(ROLES)

# permission -> rôles autorisés (table de la section 11 du PROMPT)
PERMISSIONS: dict[str, set[str]] = {
    "view_twin": ALL,
    "control_equipment": {"nurse"} | DOCTORS,
    "view_pharmacy": ALL,
    "edit_pharmacy": {"pharmacist"} | DOCTORS,
    "view_clinical": CLINICAL,  # personnel, caméras, machines, détection
    "view_command": CLINICAL,
    "manage_risks": {"nurse"} | DOCTORS,
    "view_patients": CLINICAL,
    "edit_patients": {"receptionist", "nurse"} | DOCTORS,
    "create_patients": {"receptionist"} | DOCTORS,
    "view_shift_report": CLINICAL,
    "edit_shift_report": {"nurse"} | DOCTORS,
    "view_medical_docs": CLINICAL,
    "write_medical_docs": DOCTORS,
    "view_history": CLINICAL,
    "manage_users": {"owner"},
    # V3 (Privacy by Design) : identité complète du patient (nom, prénom, date de naissance) ; les autres rôles voient le pseudonyme
    "view_identity": {"receptionist", "nurse", "duty_doctor", "general_doctor", "owner", "psychiatrist"},
    # V2 — dossier médical : lecture/écriture médecins + psychiatre, lecture infirmiers, vues restreintes sinon
    "view_medical_record": {"nurse"} | DOCTORS | PSY,
    "write_medical_record": DOCTORS | PSY,
    "view_record_identity": {"receptionist"},
    "view_record_pharmacy": {"pharmacist"},
    "open_medical_record": ALL | PSY,
    # V2 étape 4 — diagnostics live (fil médecin ↔ infirmier), ordonnance de traitement, plan de soins
    "view_diagnostics": {"nurse"} | DOCTORS | PSY,
    "decide_diagnostics": DOCTORS,
    "post_care_message": {"nurse"} | DOCTORS | PSY,
    "view_treatment_orders": {"nurse", "pharmacist"} | DOCTORS | PSY,
    "write_treatment_orders": DOCTORS,
    "view_care_plan": {"nurse"} | DOCTORS | PSY,
    "administer_medication": {"nurse"} | DOCTORS,
    # V2 étape 7 — psychologie : psychiatre en écriture, médecins en lecture complète, infirmiers en lecture (état + consignes)
    "view_psychology": {"nurse"} | DOCTORS | PSY,
    "view_psych_answers": DOCTORS | PSY,
    "write_psychology": PSY | {"owner"},
    "view_predictions": {"nurse"} | DOCTORS | PSY,
    "view_ambulances": CLINICAL,
    "manage_ambulances": {"receptionist", "nurse"} | DOCTORS,
    "run_demo": ALL,
}

ROLE_LABELS = {
    "pharmacist": "Pharmacien",
    "receptionist": "Réceptionniste",
    "nurse": "Infirmier",
    "duty_doctor": "Médecin de garde",
    "general_doctor": "Médecin généraliste",
    "owner": "Propriétaire",
    "psychiatrist": "Psychiatre / psychologue clinicien",
}


def permissions_for(role: str) -> list[str]:
    return sorted(p for p, roles in PERMISSIONS.items() if role in roles)


class CurrentUser(BaseModel):
    username: str
    role: str
    name: str = ""
    permissions: list[str] = []

    def can(self, perm: str) -> bool:
        return perm in self.permissions


# ─── Mots de passe ───────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ─── Jetons ──────────────────────────────────────────────────────────────────
def create_token(username: str, role: str, name: str = "") -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "role": role,
        "name": name,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_expire_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: Optional[str]) -> Optional[dict[str, Any]]:
    if not token:
        return None
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None


def user_from_token(token: Optional[str]) -> Optional[CurrentUser]:
    data = decode_token(token)
    if not data or data.get("role") not in ROLES:
        return None
    return CurrentUser(username=data["sub"], role=data["role"], name=data.get("name", ""), permissions=permissions_for(data["role"]))


def role_from_cookie(cookie: Optional[str]) -> Optional[str]:
    u = user_from_token(cookie)
    return u.role if u else None


def _token_from_request(request: Request) -> Optional[str]:
    token = request.cookies.get(settings.cookie_name)
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
    return token


SERVICE_USER = "n8n-service"


def service_user_from_token(token: Optional[str]) -> Optional[CurrentUser]:
    """Jeton de service (PLATFORM_SERVICE_TOKEN) : n8n appelle l'API avec le rôle owner."""
    if token and settings.platform_service_token and token == settings.platform_service_token:
        return CurrentUser(username=SERVICE_USER, role="owner", name="Service n8n", permissions=permissions_for("owner"))
    return None


def optional_user(request: Request) -> Optional[CurrentUser]:
    token = _token_from_request(request)
    user = service_user_from_token(token) or user_from_token(token)
    if user is None and not settings.auth_required:
        return CurrentUser(username="demo", role="owner", name="Mode sans authentification", permissions=permissions_for("owner"))
    return user


def get_current_user(request: Request) -> CurrentUser:
    user = optional_user(request)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentification requise")
    return user


def require(*perms: str):
    """Dépendance : l'utilisateur doit posséder toutes les permissions données."""
    unknown = [p for p in perms if p not in PERMISSIONS]
    if unknown:
        raise ValueError(f"Permission inconnue : {unknown}")

    def _dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        missing = [p for p in perms if p not in user.permissions]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Rôle « {ROLE_LABELS.get(user.role, user.role)} » : permission refusée ({', '.join(missing)})",
            )
        return user

    return _dep


# Alias nommés comme dans le PROMPT
can_edit_pharmacy = require("edit_pharmacy")
can_edit_patients = require("edit_patients")
can_manage_risks = require("manage_risks")
can_write_medical_docs = require("write_medical_docs")
can_control_equipment = require("control_equipment")
can_view_clinical = require("view_clinical")
is_owner = require("manage_users")
