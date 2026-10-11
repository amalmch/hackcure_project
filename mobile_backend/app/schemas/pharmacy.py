from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional, Any

class PharmacyBase(BaseModel):
    name: str
    address: str
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    opening_hours: Optional[Any] = None
    is_24h: bool = False
    is_active: bool = True

class PharmacyResponse(PharmacyBase):
    id: UUID
    distance_km: Optional[float] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class MedicineAvailabilityResponse(BaseModel):
    pharmacy: PharmacyResponse
    is_available: bool = True
    quantity: Optional[int] = None
    price: Optional[float] = None
    last_updated: datetime

    class Config:
        from_attributes = True
