import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload
from typing import List
from datetime import datetime
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.patient import Patient
from app.models.appointment import Appointment, AppointmentStatus
from app.schemas.appointment import AppointmentResponse, CancelAppointmentPayload

router = APIRouter(prefix="/api/v1/appointments", tags=["appointments"])

@router.get("", response_model=List[AppointmentResponse])
async def get_appointments(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    patient_res = await db.execute(select(Patient).where(Patient.user_id == current_user.id))
    patient = patient_res.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")

    result = await db.execute(
        select(Appointment)
        .options(selectinload(Appointment.doctor))
        .where(Appointment.patient_id == patient.id)
        .order_by(Appointment.appointment_date.desc(), Appointment.appointment_time.desc())
    )
    return result.scalars().all()

@router.get("/{appointment_id}", response_model=AppointmentResponse)
async def get_appointment(
    appointment_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    patient_res = await db.execute(select(Patient).where(Patient.user_id == current_user.id))
    patient = patient_res.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")

    result = await db.execute(
        select(Appointment)
        .options(selectinload(Appointment.doctor))
        .where(
            and_(
                Appointment.id == uuid.UUID(appointment_id),
                Appointment.patient_id == patient.id
            )
        )
    )
    appt = result.scalar_one_or_none()
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return appt

@router.post("/{appointment_id}/cancel", response_model=AppointmentResponse)
async def cancel_appointment(
    appointment_id: str,
    payload: CancelAppointmentPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    patient_res = await db.execute(select(Patient).where(Patient.user_id == current_user.id))
    patient = patient_res.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")

    result = await db.execute(
        select(Appointment)
        .options(selectinload(Appointment.doctor))
        .where(
            and_(
                Appointment.id == uuid.UUID(appointment_id),
                Appointment.patient_id == patient.id
            )
        )
    )
    appt = result.scalar_one_or_none()
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")

    appt.status = AppointmentStatus.CANCELLED
    appt.cancelled_by = current_user.id
    if payload.cancellation_reason:
        appt.cancellation_reason = payload.cancellation_reason

    await db.commit()
    await db.refresh(appt)
    return appt
