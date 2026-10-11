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
from app.models.dose import MedicationDose, DoseStatus
from app.schemas.dose import DoseResponse, TakeDosePayload, MissDosePayload
from app.services.dose_status import dose_response, intake_status, local_wall_time, patient_now

router = APIRouter(prefix="/api/v1/medication-doses", tags=["medication-doses"])

@router.post("/{dose_id}/take", response_model=DoseResponse)
async def take_dose(
    dose_id: uuid.UUID,
    payload: TakeDosePayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    patient_res = await db.execute(select(Patient).where(Patient.user_id == current_user.id))
    patient = patient_res.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")

    # Idempotency check if idempotency key provided
    if payload.idempotency_key:
        idem_res = await db.execute(
            select(MedicationDose)
            .options(selectinload(MedicationDose.prescription_item))
            .where(
                and_(
                    MedicationDose.idempotency_key == payload.idempotency_key,
                    MedicationDose.patient_id == patient.id,
                )
            )
        )
        existing = idem_res.scalar_one_or_none()
        if existing:
            if existing.id != dose_id:
                raise HTTPException(status_code=409, detail="Idempotency key already used")
            return existing

    result = await db.execute(
        select(MedicationDose)
        .options(selectinload(MedicationDose.prescription_item))
        .where(
            and_(
                MedicationDose.id == dose_id,
                MedicationDose.patient_id == patient.id
            )
        )
    )
    dose = result.scalar_one_or_none()
    if not dose:
        raise HTTPException(status_code=404, detail="Dose not found")

    take_time = local_wall_time(payload.taken_at, patient) if payload.taken_at else patient_now(patient).replace(tzinfo=None)
    dose.taken_at = take_time
    dose.synced = True
    if payload.idempotency_key:
        dose.idempotency_key = payload.idempotency_key

    dose.status = intake_status(dose, patient, take_time)

    await db.commit()
    await db.refresh(dose)
    return dose_response(dose, patient, take_time)

@router.post("/{dose_id}/miss", response_model=DoseResponse)
async def miss_dose(
    dose_id: uuid.UUID,
    payload: MissDosePayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    patient_res = await db.execute(select(Patient).where(Patient.user_id == current_user.id))
    patient = patient_res.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")

    result = await db.execute(
        select(MedicationDose)
        .options(selectinload(MedicationDose.prescription_item))
        .where(
            and_(
                MedicationDose.id == dose_id,
                MedicationDose.patient_id == patient.id
            )
        )
    )
    dose = result.scalar_one_or_none()
    if not dose:
        raise HTTPException(status_code=404, detail="Dose not found")

    dose.status = DoseStatus.MISSED
    if payload.notes:
        dose.notes = payload.notes

    await db.commit()
    await db.refresh(dose)
    return dose_response(dose, patient)
