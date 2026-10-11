import uuid
from datetime import datetime, date, time
from sqlalchemy import Column, String, DateTime, Date, Time, ForeignKey, Text, Enum, Integer, Boolean
from sqlalchemy import Uuid as UUID
from sqlalchemy.orm import relationship
from app.database import Base
import enum

class DoseStatus(str, enum.Enum):
    SCHEDULED = "SCHEDULED"
    DUE = "DUE"
    REMINDING = "REMINDING"
    TAKEN_ON_TIME = "TAKEN_ON_TIME"
    TAKEN_LATE = "TAKEN_LATE"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"

class MedicationDose(Base):
    __tablename__ = "medication_doses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prescription_item_id = Column(UUID(as_uuid=True), ForeignKey("prescription_items.id"))
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"), index=True)
    scheduled_date = Column(Date, index=True, nullable=False)
    scheduled_time = Column(Time, nullable=False)
    status = Column(Enum(DoseStatus), default=DoseStatus.SCHEDULED)
    taken_at = Column(DateTime, nullable=True)
    grace_period_minutes = Column(Integer, default=30)
    reminder_count = Column(Integer, default=0)
    max_reminders = Column(Integer, default=3)
    reminder_interval_minutes = Column(Integer, default=60)
    notes = Column(Text, nullable=True)
    synced = Column(Boolean, default=True)
    idempotency_key = Column(UUID(as_uuid=True), unique=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    prescription_item = relationship("PrescriptionItem")
    patient = relationship("Patient")
