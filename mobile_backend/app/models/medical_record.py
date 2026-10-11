import uuid
from datetime import datetime, date
from sqlalchemy import Column, String, DateTime, Date, ForeignKey, Text, Enum, Boolean, JSON
from sqlalchemy import Uuid as UUID
from sqlalchemy.orm import relationship
from app.database import Base
import enum

class RecordType(str, enum.Enum):
    DIAGNOSIS = "DIAGNOSIS"
    LAB_RESULT = "LAB_RESULT"
    IMAGING = "IMAGING"
    PROCEDURE = "PROCEDURE"
    VISIT_NOTE = "VISIT_NOTE"
    DOCUMENT = "DOCUMENT"

class MedicalRecord(Base):
    __tablename__ = "medical_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"))
    doctor_id = Column(UUID(as_uuid=True), ForeignKey("doctors.id"), nullable=True)
    record_type = Column(Enum(RecordType), nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    record_date = Column(Date, nullable=True)
    data = Column(JSON, nullable=True)
    file_url = Column(String, nullable=True)
    file_type = Column(String, nullable=True)
    is_confidential = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    patient = relationship("Patient")
    doctor = relationship("Doctor")
