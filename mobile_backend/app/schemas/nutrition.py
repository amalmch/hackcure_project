from pydantic import BaseModel
from uuid import UUID
from datetime import date, datetime
from typing import Optional, List, Any

class NutritionPlanBase(BaseModel):
    plan_type: Optional[str] = None
    recommended_foods: Optional[List[str]] = []
    foods_to_avoid: Optional[List[str]] = []
    meal_recommendations: Optional[Any] = None
    hydration_ml_daily: Optional[int] = None
    calories_target: Optional[int] = None
    doctor_notes: Optional[str] = None
    dietitian_notes: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: str

class NutritionPlanResponse(NutritionPlanBase):
    id: UUID
    prescription_id: Optional[UUID] = None
    patient_id: UUID
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
