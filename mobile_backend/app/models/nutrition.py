import uuid
from datetime import datetime, date
from sqlalchemy import Column, String, DateTime, Date, ForeignKey, Text, Enum, Integer, JSON
from sqlalchemy import Uuid as UUID
from app.database import Base
import enum

class NutritionPlanStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"

class NutritionPlan(Base):
    __tablename__ = "nutrition_plans"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prescription_id = Column(UUID(as_uuid=True), ForeignKey("prescriptions.id"), nullable=True)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"))
    plan_type = Column(String, nullable=True)
    recommended_foods = Column(JSON, nullable=True)
    foods_to_avoid = Column(JSON, nullable=True)
    meal_recommendations = Column(JSON, nullable=True)
    hydration_ml_daily = Column(Integer, nullable=True)
    calories_target = Column(Integer, nullable=True)
    doctor_notes = Column(Text, nullable=True)
    dietitian_notes = Column(Text, nullable=True)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    status = Column(Enum(NutritionPlanStatus), default=NutritionPlanStatus.ACTIVE)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
