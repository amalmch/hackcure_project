import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.doctor import Doctor
from app.schemas.doctor import DoctorResponse

router = APIRouter(prefix="/api/v1/doctors", tags=["doctors"])

@router.get("/{doctor_id}", response_model=DoctorResponse)
async def get_doctor_by_id(
    doctor_id: str,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Doctor).where(Doctor.id == uuid.UUID(doctor_id)))
    doctor = result.scalar_one_or_none()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    return doctor
