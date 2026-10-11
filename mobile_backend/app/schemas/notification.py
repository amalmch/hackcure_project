from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional, List, Any

class NotificationResponse(BaseModel):
    id: UUID
    user_id: UUID
    title: str
    body: Optional[str] = None
    category: str
    priority: str
    is_read: bool = False
    read_at: Optional[datetime] = None
    data: Optional[Any] = None
    created_at: datetime

    class Config:
        from_attributes = True

class PaginatedNotificationResponse(BaseModel):
    items: List[NotificationResponse]
    total: int
    page: int
    limit: int
    total_pages: int
