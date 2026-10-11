import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.patient import Patient
from app.models.prescription import Prescription
from app.schemas.prescription import PrescriptionResponse

router = APIRouter(prefix="/api/v1/prescriptions", tags=["prescriptions"])

@router.get("/{prescription_id}", response_model=PrescriptionResponse)
async def get_prescription_by_id(
    prescription_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    patient_res = await db.execute(select(Patient).where(Patient.user_id == current_user.id))
    patient = patient_res.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")

    result = await db.execute(
        select(Prescription)
        .options(selectinload(Prescription.doctor), selectinload(Prescription.items))
        .where(
            Prescription.id == uuid.UUID(prescription_id),
            Prescription.patient_id == patient.id
        )
    )
    prescription = result.scalar_one_or_none()
    if not prescription:
        raise HTTPException(status_code=404, detail="Prescription not found")
        
    return prescription
