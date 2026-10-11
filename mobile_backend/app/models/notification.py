import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Enum, Boolean, JSON
from sqlalchemy import Uuid as UUID
from app.database import Base
import enum

class NotificationCategory(str, enum.Enum):
    MEDICATION = "MEDICATION"
    DOCTOR = "DOCTOR"
    PRESCRIPTION = "PRESCRIPTION"
    APPOINTMENT = "APPOINTMENT"
    PHARMACY = "PHARMACY"
    SYSTEM = "SYSTEM"

class NotificationPriority(str, enum.Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"

class Notification(Base):
    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    title = Column(String, nullable=False)
    body = Column(Text, nullable=True)
    category = Column(Enum(NotificationCategory), nullable=False)
    priority = Column(Enum(NotificationPriority), default=NotificationPriority.NORMAL)
    is_read = Column(Boolean, default=False)
    read_at = Column(DateTime, nullable=True)
    data = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
