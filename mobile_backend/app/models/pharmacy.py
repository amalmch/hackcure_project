import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Float, Boolean, JSON, ForeignKey, Numeric, Integer, UniqueConstraint
from sqlalchemy import Uuid as UUID
from app.database import Base

class Pharmacy(Base):
    __tablename__ = "pharmacies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    address = Column(String, nullable=False)
    city = Column(String, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)
    opening_hours = Column(JSON, nullable=True)
    is_24h = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class PharmacyInventory(Base):
    __tablename__ = "pharmacy_inventory"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pharmacy_id = Column(UUID(as_uuid=True), ForeignKey("pharmacies.id"))
    medication_name = Column(String, index=True, nullable=False)
    active_ingredient = Column(String, nullable=True)
    dosage = Column(String, nullable=True)
    form = Column(String, nullable=True)
    is_available = Column(Boolean, default=True)
    quantity = Column(Integer, nullable=True)
    price = Column(Float, nullable=True)
    last_updated = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        UniqueConstraint('pharmacy_id', 'medication_name', 'dosage', name='uix_pharmacy_med_dosage'),
    )
