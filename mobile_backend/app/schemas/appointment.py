from pydantic import BaseModel
from uuid import UUID
from datetime import date, time, datetime
from typing import Optional
from app.schemas.doctor import DoctorResponse

class CancelAppointmentPayload(BaseModel):
    cancellation_reason: Optional[str] = None

class AppointmentResponse(BaseModel):
    id: UUID
    patient_id: UUID
    doctor_id: UUID
    appointment_date: date
    appointment_time: time
    duration_minutes: int = 30
    appointment_type: str
    status: str
    clinic_name: Optional[str] = None
    clinic_address: Optional[str] = None
    reason: Optional[str] = None
    notes: Optional[str] = None
    cancellation_reason: Optional[str] = None
    cancelled_by: Optional[UUID] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    doctor: Optional[DoctorResponse] = None

    class Config:
        from_attributes = True
