from app.api.auth import router as auth_router
from app.api.patients import router as patients_router
from app.api.prescriptions import router as prescriptions_router
from app.api.doses import router as doses_router
from app.api.sport import router as sport_router
from app.api.pharmacies import router as pharmacies_router
from app.api.conversations import router as conversations_router
from app.api.appointments import router as appointments_router
from app.api.medical_records import router as medical_records_router
from app.api.notifications import router as notifications_router
from app.api.doctors import router as doctors_router
from app.api.automation import router as automation_router
from app.api.companion import router as companion_router
from app.api.sakina import router as sakina_router

__all__ = [
    "auth_router",
    "patients_router",
    "prescriptions_router",
    "doses_router",
    "sport_router",
    "pharmacies_router",
    "conversations_router",
    "appointments_router",
    "medical_records_router",
    "notifications_router",
    "doctors_router",
    "automation_router",
    "companion_router",
    "sakina_router",
]
