"""Gestion des utilisateurs (owner uniquement)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import auth as authlib
from ..audit import audit
from ..db import get_session
from ..models import User

router = APIRouter(prefix="/api/users", tags=["users"])


class UserIn(BaseModel):
    username: str
    password: str
    role: str
    full_name: str = ""
    active: bool = True


class UserPatch(BaseModel):
    password: Optional[str] = None
    role: Optional[str] = None
    full_name: Optional[str] = None
    active: Optional[bool] = None


def _out(u: User) -> dict:
    return {"id": u.id, "username": u.username, "role": u.role, "role_label": authlib.ROLE_LABELS.get(u.role, u.role), "full_name": u.full_name, "active": u.active, "created_at": u.created_at}


@router.get("")
def list_users(session: Session = Depends(get_session), _: authlib.CurrentUser = Depends(authlib.is_owner)):
    return [_out(u) for u in session.exec(select(User).order_by(User.id)).all()]


@router.post("", status_code=201)
def create_user(body: UserIn, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.is_owner)):
    if body.role not in authlib.ROLES:
        raise HTTPException(400, "Rôle inconnu")
    uname = body.username.strip().lower()
    if session.exec(select(User).where(User.username == uname)).first():
        raise HTTPException(409, "Identifiant déjà utilisé")
    row = User(username=uname, hashed_password=authlib.hash_password(body.password), role=body.role, full_name=body.full_name, active=body.active)
    session.add(row)
    session.flush()
    audit(session, user, "create", "user", row.id, {"username": uname, "role": body.role})
    session.commit()
    session.refresh(row)
    return _out(row)


@router.patch("/{user_id}")
def patch_user(user_id: int, body: UserPatch, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.is_owner)):
    row = session.get(User, user_id)
    if not row:
        raise HTTPException(404, "Utilisateur introuvable")
    if body.role is not None:
        if body.role not in authlib.ROLES:
            raise HTTPException(400, "Rôle inconnu")
        row.role = body.role
    if body.password:
        row.hashed_password = authlib.hash_password(body.password)
    if body.full_name is not None:
        row.full_name = body.full_name
    if body.active is not None:
        row.active = body.active
    audit(session, user, "update", "user", row.id, body.model_dump(exclude_none=True, exclude={"password"}))
    session.commit()
    session.refresh(row)
    return _out(row)


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: int, session: Session = Depends(get_session), user: authlib.CurrentUser = Depends(authlib.is_owner)):
    row = session.get(User, user_id)
    if not row:
        raise HTTPException(404, "Utilisateur introuvable")
    if row.username == user.username:
        raise HTTPException(400, "Impossible de supprimer son propre compte")
    session.delete(row)
    audit(session, user, "delete", "user", user_id)
    session.commit()
    return None
