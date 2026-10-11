from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from app.schemas.dose import DoseResponse
from app.schemas.appointment import AppointmentResponse
from app.schemas.sport import SportActivityResponse

class DailyAdherence(BaseModel):
    date: str
    percentage: float
    taken: int
    total: int

class DailyIntakeCounts(BaseModel):
    total: int
    taken_on_time: int
    taken_late: int
    missed: int
    pending: int
    percentage: float

class WeeklyAdherence(BaseModel):
    percentage: float
    total: int = 0
    taken_on_time: int = 0
    taken_late: int = 0
    missed: int = 0
    daily_breakdown: List[DailyAdherence]

class MonthlyAdherence(BaseModel):
    total: int
    taken_on_time: int
    taken_late: int
    missed: int
    percentage: float

class AdherenceStatsResponse(BaseModel):
    overall_percentage: float
    total_doses_scheduled: int
    total_doses_taken: int
    total_doses_missed: int
    current_streak_days: int
    longest_streak_days: int
    daily: DailyIntakeCounts
    weekly: WeeklyAdherence
    monthly: MonthlyAdherence

class DashboardDataResponse(BaseModel):
    today_doses: List[DoseResponse]
    medication_progress: Dict[str, int | float]
    sport_progress: Dict[str, int | float]
    today_sport_activities: List[SportActivityResponse]
    adherence: AdherenceStatsResponse
    next_appointment: Optional[AppointmentResponse] = None
    active_prescriptions_count: int
    recent_sport_activity: Optional[SportActivityResponse] = None
    unread_notifications_count: int
