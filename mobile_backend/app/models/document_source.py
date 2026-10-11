import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Enum, Integer, JSON
from sqlalchemy import Uuid as UUID
from sqlalchemy.orm import relationship
from app.database import Base
import enum

class DocumentType(str, enum.Enum):
    DOCTOR_REPORT = "DOCTOR_REPORT"
    PRESCRIPTION = "PRESCRIPTION"

class DocumentStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    APPLIED = "APPLIED"
    FAILED = "FAILED"

class DocumentSource(Base):
    __tablename__ = "document_sources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"))
    document_type = Column(Enum(DocumentType), nullable=False)
    original_filename = Column(String, nullable=True)
    file_url = Column(String, nullable=True)
    upload_date = Column(DateTime, default=datetime.utcnow)
    status = Column(Enum(DocumentStatus), default=DocumentStatus.PENDING)
    version = Column(Integer, default=1)
    extracted_data = Column(JSON, nullable=True)
    confidence_scores = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    applied_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    patient = relationship("Patient")
