from pydantic import BaseModel
from uuid import UUID
from datetime import date, datetime
from typing import Optional, Any
from app.schemas.doctor import DoctorResponse

class MedicalRecordResponse(BaseModel):
    id: UUID
    patient_id: UUID
    doctor_id: Optional[UUID] = None
    record_type: str
    title: str
    description: Optional[str] = None
    record_date: Optional[date] = None
    data: Optional[Any] = None
    file_url: Optional[str] = None
    file_type: Optional[str] = None
    is_confidential: bool = False
    created_at: datetime
    updated_at: Optional[datetime] = None
    doctor: Optional[DoctorResponse] = None

    class Config:
        from_attributes = True
