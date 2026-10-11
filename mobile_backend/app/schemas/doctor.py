from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional

class DoctorBase(BaseModel):
    first_name: str
    last_name: str
    specialty: str
    license_number: Optional[str] = None
    clinic_name: Optional[str] = None
    clinic_address: Optional[str] = None
    clinic_phone: Optional[str] = None
    avatar_url: Optional[str] = None
    bio: Optional[str] = None

class DoctorCreate(DoctorBase):
    user_id: UUID

class DoctorResponse(DoctorBase):
    id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
