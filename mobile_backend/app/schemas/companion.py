from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_serializer


class UTCResponse(BaseModel):
    @field_serializer("created_at", "updated_at", "sent_at", check_fields=False)
    def serialize_utc_datetime(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return aware.isoformat().replace("+00:00", "Z")


class ConsentUpdate(BaseModel):
    chat_consent: bool
    share_with_doctor: bool = False


class ConsentResponse(UTCResponse):
    chat_consent: bool
    share_with_doctor: bool
    updated_at: Optional[datetime] = None


class MessageCreate(BaseModel):
    conversation_id: Optional[UUID] = None
    client_message_id: Optional[UUID] = None
    content: str = Field(min_length=1, max_length=2000)


class MessageResponse(UTCResponse):
    id: UUID
    conversation_id: UUID
    role: str
    content: str
    triage_label: Optional[str] = None
    language: Optional[str] = None
    created_at: datetime
    fallback: bool = False
    error_code: Optional[str] = None


class CompanionUpstreamResponse(BaseModel):
    reply: str = Field(min_length=1, max_length=5000)
    triage_label: Optional[str] = None
    language: Optional[str] = None
    safety_flag: bool = False
    fallback: bool = False
    error_code: Optional[str] = None


class ConversationResponse(UTCResponse):
    id: UUID
    created_at: datetime
    updated_at: datetime


class MoodCreate(BaseModel):
    mood: int = Field(ge=1, le=5)
    note: Optional[str] = Field(default=None, max_length=240)


class MoodResponse(UTCResponse):
    id: UUID
    mood: int
    note: Optional[str]
    created_at: datetime
