import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Boolean, Integer, JSON
from sqlalchemy import Uuid as UUID
from sqlalchemy.orm import relationship
from app.database import Base

class TreatmentSummary(Base):
    __tablename__ = "treatment_summaries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"))
    document_source_id = Column(UUID(as_uuid=True), ForeignKey("document_sources.id"), nullable=True)
    version = Column(Integer, default=1)
    is_current = Column(Boolean, default=True)
    diagnosis = Column(Text, nullable=True)
    treatment_goals = Column(JSON, nullable=True)
    precautions = Column(JSON, nullable=True)
    warnings = Column(JSON, nullable=True)
    follow_up_dates = Column(JSON, nullable=True)
    consultation_reason = Column(Text, nullable=True)
    doctor_conclusion = Column(Text, nullable=True)
    patient_summary = Column(Text, nullable=True)
    sport_recommendations = Column(JSON, nullable=True)
    nutrition_recommendations = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    patient = relationship("Patient")
    document_source = relationship("DocumentSource")
