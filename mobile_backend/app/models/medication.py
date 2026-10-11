import uuid
from datetime import datetime, date
from sqlalchemy import Column, String, DateTime, Date, ForeignKey, Text, Enum, Integer, Boolean, JSON
from sqlalchemy import Uuid as UUID
from sqlalchemy.orm import relationship
from app.database import Base
import enum

class MedicationForm(str, enum.Enum):
    TABLET = "TABLET"
    CAPSULE = "CAPSULE"
    SYRUP = "SYRUP"
    INJECTION = "INJECTION"
    CREAM = "CREAM"
    DROPS = "DROPS"
    INHALER = "INHALER"
    OTHER = "OTHER"

class PrescriptionItem(Base):
    __tablename__ = "prescription_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prescription_id = Column(UUID(as_uuid=True), ForeignKey("prescriptions.id"))
    medication_name = Column(String, nullable=False)
    active_ingredient = Column(String, nullable=True)
    dosage = Column(String, nullable=False)
    form = Column(Enum(MedicationForm), nullable=True)
    frequency = Column(String, nullable=False)
    frequency_per_day = Column(Integer, nullable=True)
    scheduled_times = Column(JSON, nullable=True)
    duration_days = Column(Integer, nullable=True)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    instructions = Column(Text, nullable=True)
    before_food = Column(Boolean, nullable=True)
    doctor_notes = Column(Text, nullable=True)
    quantity_prescribed = Column(Integer, nullable=True)
    refills_remaining = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    prescription = relationship("Prescription", backref="items")
