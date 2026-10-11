from pydantic import BaseModel
from uuid import UUID
from datetime import date, time, datetime
from typing import Optional, List, Any

class SportPlanBase(BaseModel):
    activity_name: str
    activity_type: str
    duration_minutes: Optional[int] = None
    intensity: Optional[str] = None
    frequency_per_week: Optional[int] = None
    scheduled_days: Optional[List[str]] = None
    scheduled_time: Optional[time] = None
    instructions: Optional[str] = None
    doctor_notes: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: str

class SportPlanResponse(SportPlanBase):
    id: UUID
    prescription_id: Optional[UUID] = None
    patient_id: UUID
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class CompleteActivityPayload(BaseModel):
    duration_minutes: Optional[int] = None
    notes: Optional[str] = None

class SportActivityResponse(BaseModel):
    id: UUID
    sport_plan_id: UUID
    patient_id: UUID
    scheduled_date: date
    scheduled_time: Optional[time] = None
    status: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_actual_minutes: Optional[int] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    sport_plan: Optional[SportPlanResponse] = None

    class Config:
        from_attributes = True
