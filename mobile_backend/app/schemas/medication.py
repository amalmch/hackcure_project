from pydantic import BaseModel
from uuid import UUID
from datetime import date, datetime
from typing import Optional, List, Any

class PrescriptionItemBase(BaseModel):
    medication_name: str
    active_ingredient: Optional[str] = None
    dosage: str
    form: Optional[str] = None
    frequency: str
    frequency_per_day: Optional[int] = None
    scheduled_times: Optional[List[str]] = None
    duration_days: Optional[int] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    instructions: Optional[str] = None
    before_food: Optional[bool] = None
    doctor_notes: Optional[str] = None

class PrescriptionItemResponse(PrescriptionItemBase):
    id: UUID
    prescription_id: UUID
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
