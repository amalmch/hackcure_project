import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func
from typing import List, Optional
import math
from app.database import get_db
from app.models.pharmacy import Pharmacy, PharmacyInventory
from app.schemas.pharmacy import PharmacyResponse, MedicineAvailabilityResponse

router = APIRouter(tags=["pharmacies"])

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0 # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 2)

@router.get("/api/v1/pharmacies/nearby", response_model=List[PharmacyResponse])
async def get_nearby_pharmacies(
    lat: float = Query(...),
    lng: float = Query(...),
    radius: float = Query(10.0),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Pharmacy).where(Pharmacy.is_active == True))
    all_pharmacies = result.scalars().all()
    
    nearby = []
    for pharm in all_pharmacies:
        if pharm.latitude is not None and pharm.longitude is not None:
            dist = haversine(lat, lng, pharm.latitude, pharm.longitude)
            if dist <= radius:
                # Attach computed distance
                p_dict = PharmacyResponse.model_validate(pharm).model_dump()
                p_dict["distance_km"] = dist
                nearby.append(p_dict)
    
    nearby.sort(key=lambda x: x["distance_km"] or 9999)
    return nearby

@router.get("/api/v1/pharmacies/search", response_model=List[PharmacyResponse])
async def search_pharmacies(
    q: str = Query(...),
    db: AsyncSession = Depends(get_db)
):
    search_term = f"%{q}%"
    result = await db.execute(
        select(Pharmacy).where(
            or_(
                Pharmacy.name.ilike(search_term),
                Pharmacy.address.ilike(search_term),
                Pharmacy.city.ilike(search_term)
            )
        )
    )
    return result.scalars().all()

@router.get("/api/v1/pharmacies/{pharmacy_id}", response_model=PharmacyResponse)
async def get_pharmacy_by_id(
    pharmacy_id: str,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Pharmacy).where(Pharmacy.id == uuid.UUID(pharmacy_id)))
    pharmacy = result.scalar_one_or_none()
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")
    return pharmacy

@router.get("/api/v1/medicines/{medication_name}/availability", response_model=List[MedicineAvailabilityResponse])
async def get_medicine_availability(
    medication_name: str,
    lat: Optional[float] = Query(None),
    lng: Optional[float] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    search_term = f"%{medication_name}%"
    result = await db.execute(
        select(PharmacyInventory, Pharmacy)
        .join(Pharmacy, PharmacyInventory.pharmacy_id == Pharmacy.id)
        .where(
            or_(
                PharmacyInventory.medication_name.ilike(search_term),
                PharmacyInventory.active_ingredient.ilike(search_term)
            )
        )
    )
    rows = result.all()
    availability = []
    for inv, pharm in rows:
        dist = None
        if lat is not None and lng is not None and pharm.latitude and pharm.longitude:
            dist = haversine(lat, lng, pharm.latitude, pharm.longitude)
        
        p_dict = PharmacyResponse.model_validate(pharm).model_dump()
        p_dict["distance_km"] = dist

        availability.append(MedicineAvailabilityResponse(
            pharmacy=PharmacyResponse(**p_dict),
            is_available=inv.is_available,
            quantity=inv.quantity,
            price=inv.price,
            last_updated=inv.last_updated or inv.created_at
        ))

    if lat is not None and lng is not None:
        availability.sort(key=lambda x: x.pharmacy.distance_km if x.pharmacy.distance_km is not None else 9999)

    return availability
