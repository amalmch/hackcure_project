from pydantic import BaseModel
from uuid import UUID
from datetime import date, time, datetime
from typing import Optional
from app.schemas.medication import PrescriptionItemResponse

class TakeDosePayload(BaseModel):
    idempotency_key: Optional[UUID] = None
    taken_at: Optional[datetime] = None

class MissDosePayload(BaseModel):
    notes: Optional[str] = None

class DoseResponse(BaseModel):
    id: UUID
    prescription_item_id: UUID
    patient_id: UUID
    scheduled_date: date
    scheduled_time: time
    status: str
    taken_at: Optional[datetime] = None
    grace_period_minutes: int = 30
    reminder_count: int = 0
    max_reminders: int = 3
    notes: Optional[str] = None
    synced: bool = True
    idempotency_key: Optional[UUID] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    prescription_item: Optional[PrescriptionItemResponse] = None

    class Config:
        from_attributes = True
