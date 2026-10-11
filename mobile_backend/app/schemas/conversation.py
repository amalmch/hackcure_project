from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional
from app.schemas.doctor import DoctorResponse

class CreateConversationPayload(BaseModel):
    doctor_id: UUID
    category: str
    subject: Optional[str] = None
    initial_message: str

class SendMessagePayload(BaseModel):
    content: str

class MessageResponse(BaseModel):
    id: UUID
    conversation_id: UUID
    sender_id: UUID
    sender_role: str
    content: str
    message_type: str = "TEXT"
    is_read: bool = False
    read_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True

class ConversationResponse(BaseModel):
    id: UUID
    patient_id: UUID
    doctor_id: UUID
    subject: Optional[str] = None
    category: Optional[str] = None
    status: str
    last_message_at: datetime
    created_at: datetime
    updated_at: Optional[datetime] = None
    doctor: Optional[DoctorResponse] = None
    last_message: Optional[MessageResponse] = None
    unread_count: int = 0

    class Config:
        from_attributes = True
