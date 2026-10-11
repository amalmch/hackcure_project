import uuid
from datetime import datetime, date, time
from sqlalchemy import Column, String, DateTime, Date, Time, ForeignKey, Text, Enum, Integer, JSON
from sqlalchemy import Uuid as UUID
from sqlalchemy.orm import relationship
from app.database import Base
import enum

class ActivityType(str, enum.Enum):
    WALKING = "WALKING"
    RUNNING = "RUNNING"
    SWIMMING = "SWIMMING"
    CYCLING = "CYCLING"
    YOGA = "YOGA"
    STRETCHING = "STRETCHING"
    OTHER = "OTHER"

class Intensity(str, enum.Enum):
    LIGHT = "LIGHT"
    MODERATE = "MODERATE"
    VIGOROUS = "VIGOROUS"

class PlanStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"

class SportPlan(Base):
    __tablename__ = "sport_plans"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prescription_id = Column(UUID(as_uuid=True), ForeignKey("prescriptions.id"), nullable=True)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"))
    activity_name = Column(String, nullable=False)
    activity_type = Column(Enum(ActivityType), nullable=False)
    duration_minutes = Column(Integer, nullable=True)
    intensity = Column(Enum(Intensity), nullable=True)
    frequency_per_week = Column(Integer, nullable=True)
    scheduled_days = Column(JSON, nullable=True)
    scheduled_time = Column(Time, nullable=True)
    instructions = Column(Text, nullable=True)
    doctor_notes = Column(Text, nullable=True)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    status = Column(Enum(PlanStatus), default=PlanStatus.ACTIVE)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ActivityStatus(str, enum.Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"

class SportActivity(Base):
    __tablename__ = "sport_activities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sport_plan_id = Column(UUID(as_uuid=True), ForeignKey("sport_plans.id"))
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"))
    scheduled_date = Column(Date, nullable=False)
    scheduled_time = Column(Time, nullable=True)
    status = Column(Enum(ActivityStatus), default=ActivityStatus.SCHEDULED)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    duration_actual_minutes = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    sport_plan = relationship("SportPlan")
    patient = relationship("Patient")
