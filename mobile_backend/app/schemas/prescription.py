from pydantic import BaseModel
from uuid import UUID
from datetime import date, datetime
from typing import Optional, List
from app.schemas.doctor import DoctorResponse
from app.schemas.medication import PrescriptionItemResponse

class PrescriptionBase(BaseModel):
    diagnosis: Optional[str] = None
    notes: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: str

class PrescriptionResponse(PrescriptionBase):
    id: UUID
    patient_id: UUID
    doctor_id: Optional[UUID] = None
    prescription_number: Optional[str] = None
    version: Optional[int] = 1
    is_current: Optional[bool] = True
    created_at: datetime
    updated_at: Optional[datetime] = None
    doctor: Optional[DoctorResponse] = None
    items: Optional[List[PrescriptionItemResponse]] = []

    class Config:
        from_attributes = True
