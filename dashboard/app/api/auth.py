"""Connexion / déconnexion / profil courant."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import auth as authlib
from ..audit import audit
from ..config import settings
from ..db import get_session
from ..models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


def _user_payload(u: authlib.CurrentUser) -> dict:
    return {
        "username": u.username,
        "role": u.role,
        "role_label": authlib.ROLE_LABELS.get(u.role, u.role),
        "name": u.name,
        "permissions": u.permissions,
    }


@router.post("/login")
def login(body: LoginIn, response: Response, session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.username == body.username.strip().lower())).first()
    if not user or not user.active or not authlib.verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Identifiant ou mot de passe incorrect")
    token = authlib.create_token(user.username, user.role, user.full_name)
    response.set_cookie(
        settings.cookie_name,
        token,
        httponly=True,
        samesite="lax",
        max_age=settings.jwt_expire_minutes * 60,
        path="/",
    )
    cu = authlib.CurrentUser(username=user.username, role=user.role, name=user.full_name, permissions=authlib.permissions_for(user.role))
    audit(session, cu, "login", "user", user.id)
    session.commit()
    return {"status": "ok", "user": _user_payload(cu), "token": token}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(settings.cookie_name, path="/")
    return {"status": "ok"}


@router.get("/me")
def me(user: authlib.CurrentUser = Depends(authlib.get_current_user)):
    return _user_payload(user)


@router.get("/roles")
def roles():
    return {
        "roles": [{"role": r, "label": authlib.ROLE_LABELS[r], "permissions": authlib.permissions_for(r)} for r in authlib.ROLES],
        "permissions": sorted(authlib.PERMISSIONS.keys()),
    }
