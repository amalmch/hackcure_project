import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload
from datetime import datetime
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.patient import Patient
from app.models.sport import SportActivity, ActivityStatus
from app.schemas.sport import SportActivityResponse, CompleteActivityPayload

router = APIRouter(prefix="/api/v1/sport-activities", tags=["sport-activities"])

@router.post("/{activity_id}/start", response_model=SportActivityResponse)
async def start_sport_activity(
    activity_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    patient_res = await db.execute(select(Patient).where(Patient.user_id == current_user.id))
    patient = patient_res.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")

    result = await db.execute(
        select(SportActivity)
        .options(selectinload(SportActivity.sport_plan))
        .where(
            and_(
                SportActivity.id == uuid.UUID(activity_id),
                SportActivity.patient_id == patient.id
            )
        )
    )
    activity = result.scalar_one_or_none()
    if not activity:
        raise HTTPException(status_code=404, detail="Sport activity not found")

    activity.status = ActivityStatus.IN_PROGRESS
    activity.started_at = datetime.utcnow()

    await db.commit()
    await db.refresh(activity)
    return activity

@router.post("/{activity_id}/complete", response_model=SportActivityResponse)
async def complete_sport_activity(
    activity_id: str,
    payload: CompleteActivityPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    patient_res = await db.execute(select(Patient).where(Patient.user_id == current_user.id))
    patient = patient_res.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")

    result = await db.execute(
        select(SportActivity)
        .options(selectinload(SportActivity.sport_plan))
        .where(
            and_(
                SportActivity.id == uuid.UUID(activity_id),
                SportActivity.patient_id == patient.id
            )
        )
    )
    activity = result.scalar_one_or_none()
    if not activity:
        raise HTTPException(status_code=404, detail="Sport activity not found")

    now = datetime.utcnow()
    activity.status = ActivityStatus.COMPLETED
    activity.completed_at = now
    if payload.duration_minutes is not None:
        activity.duration_actual_minutes = payload.duration_minutes
    elif activity.started_at:
        activity.duration_actual_minutes = max(1, int((now - activity.started_at).total_seconds() / 60))
    if payload.notes:
        activity.notes = payload.notes

    await db.commit()
    await db.refresh(activity)
    return activity
