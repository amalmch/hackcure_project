import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload
from typing import List
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.patient import Patient
from app.models.medical_record import MedicalRecord
from app.schemas.medical_record import MedicalRecordResponse

router = APIRouter(prefix="/api/v1/medical-records", tags=["medical-records"])

@router.get("", response_model=List[MedicalRecordResponse])
async def get_medical_records(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    patient_res = await db.execute(select(Patient).where(Patient.user_id == current_user.id))
    patient = patient_res.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")

    result = await db.execute(
        select(MedicalRecord)
        .options(selectinload(MedicalRecord.doctor))
        .where(MedicalRecord.patient_id == patient.id)
        .order_by(MedicalRecord.record_date.desc(), MedicalRecord.created_at.desc())
    )
    return result.scalars().all()

@router.get("/{record_id}", response_model=MedicalRecordResponse)
async def get_medical_record(
    record_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    patient_res = await db.execute(select(Patient).where(Patient.user_id == current_user.id))
    patient = patient_res.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")

    result = await db.execute(
        select(MedicalRecord)
        .options(selectinload(MedicalRecord.doctor))
        .where(
            and_(
                MedicalRecord.id == uuid.UUID(record_id),
                MedicalRecord.patient_id == patient.id
            )
        )
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Medical record not found")
    return record
