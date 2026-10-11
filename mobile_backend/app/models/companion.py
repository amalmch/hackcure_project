import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy import Uuid as UUID

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CompanionConversation(Base):
    __tablename__ = "companion_conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False, index=True)
    rolling_summary = Column(Text, nullable=False, default="")
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class CompanionMessage(Base):
    __tablename__ = "companion_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("companion_conversations.id"), nullable=False, index=True)
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    triage_label = Column(String(32), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class CompanionConsent(Base):
    __tablename__ = "companion_consents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False, unique=True, index=True)
    chat_consent = Column(Boolean, nullable=False, default=False)
    share_with_doctor = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class MoodEntry(Base):
    __tablename__ = "mood_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False, index=True)
    mood = Column(Integer, nullable=False)
    note = Column(String(240), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class SafetyEvent(Base):
    __tablename__ = "safety_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False, index=True)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("companion_conversations.id"), nullable=False)
    category = Column(String(32), nullable=False)
    source = Column(String(16), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
