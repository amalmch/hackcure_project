import os

base_dir = r"c:\Users\moham\Desktop\hackcure\backend"

files_to_create = {
    "app/schemas/prescription.py": '''from pydantic import BaseModel\nfrom uuid import UUID\nfrom datetime import date, datetime\nfrom typing import Optional, List\n\nclass PrescriptionBase(BaseModel):\n    diagnosis: Optional[str] = None\n    notes: Optional[str] = None\n    start_date: Optional[date] = None\n    end_date: Optional[date] = None\n\nclass PrescriptionResponse(PrescriptionBase):\n    id: UUID\n    patient_id: UUID\n    doctor_id: UUID\n    prescription_number: Optional[str] = None\n    status: str\n    created_at: datetime\n\n    class Config:\n        from_attributes = True\n''',
    
    "app/schemas/medication.py": '''from pydantic import BaseModel\nfrom uuid import UUID\nfrom datetime import date, datetime\nfrom typing import Optional, List\n\nclass MedicationBase(BaseModel):\n    medication_name: str\n    active_ingredient: Optional[str] = None\n    dosage: str\n    form: Optional[str] = None\n    frequency: str\n    frequency_per_day: Optional[int] = None\n    instructions: Optional[str] = None\n    before_food: Optional[bool] = None\n\nclass MedicationResponse(MedicationBase):\n    id: UUID\n    prescription_id: UUID\n    duration_days: Optional[int] = None\n    start_date: Optional[date] = None\n    end_date: Optional[date] = None\n    created_at: datetime\n\n    class Config:\n        from_attributes = True\n''',

    "app/schemas/dose.py": '''from pydantic import BaseModel\nfrom uuid import UUID\nfrom datetime import date, time, datetime\nfrom typing import Optional\n\nclass DoseResponse(BaseModel):\n    id: UUID\n    prescription_item_id: UUID\n    patient_id: UUID\n    scheduled_date: date\n    scheduled_time: time\n    status: str\n    taken_at: Optional[datetime] = None\n    notes: Optional[str] = None\n    \n    class Config:\n        from_attributes = True\n''',

    "app/schemas/sport.py": '''from pydantic import BaseModel\nfrom uuid import UUID\nfrom datetime import date, time, datetime\nfrom typing import Optional, List\n\nclass SportPlanResponse(BaseModel):\n    id: UUID\n    activity_name: str\n    activity_type: str\n    duration_minutes: Optional[int]\n    intensity: Optional[str]\n    frequency_per_week: Optional[int]\n    status: str\n\n    class Config:\n        from_attributes = True\n''',

    "app/schemas/nutrition.py": '''from pydantic import BaseModel\nfrom uuid import UUID\nfrom datetime import date, datetime\nfrom typing import Optional\n\nclass NutritionPlanResponse(BaseModel):\n    id: UUID\n    plan_type: Optional[str]\n    calories_target: Optional[int]\n    status: str\n\n    class Config:\n        from_attributes = True\n''',

    "app/schemas/pharmacy.py": '''from pydantic import BaseModel\nfrom uuid import UUID\nfrom typing import Optional\n\nclass PharmacyResponse(BaseModel):\n    id: UUID\n    name: str\n    address: str\n    city: Optional[str]\n    latitude: Optional[float]\n    longitude: Optional[float]\n    is_24h: bool\n\n    class Config:\n        from_attributes = True\n''',

    "app/schemas/conversation.py": '''from pydantic import BaseModel\nfrom uuid import UUID\nfrom typing import Optional\nfrom datetime import datetime\n\nclass ConversationResponse(BaseModel):\n    id: UUID\n    subject: Optional[str]\n    category: Optional[str]\n    status: str\n    last_message_at: datetime\n\n    class Config:\n        from_attributes = True\n''',

    "app/schemas/appointment.py": '''from pydantic import BaseModel\nfrom uuid import UUID\nfrom datetime import date, time\nfrom typing import Optional\n\nclass AppointmentResponse(BaseModel):\n    id: UUID\n    appointment_date: date\n    appointment_time: time\n    duration_minutes: int\n    appointment_type: str\n    status: str\n    clinic_name: Optional[str]\n\n    class Config:\n        from_attributes = True\n''',

    "app/schemas/medical_record.py": '''from pydantic import BaseModel\nfrom uuid import UUID\nfrom typing import Optional\nfrom datetime import date\n\nclass MedicalRecordResponse(BaseModel):\n    id: UUID\n    record_type: str\n    title: str\n    description: Optional[str]\n    record_date: Optional[date]\n\n    class Config:\n        from_attributes = True\n''',

    "app/schemas/notification.py": '''from pydantic import BaseModel\nfrom uuid import UUID\nfrom datetime import datetime\nfrom typing import Optional\n\nclass NotificationResponse(BaseModel):\n    id: UUID\n    title: str\n    body: Optional[str]\n    category: str\n    is_read: bool\n    created_at: datetime\n\n    class Config:\n        from_attributes = True\n''',

    "app/schemas/dashboard.py": '''from pydantic import BaseModel\nfrom typing import List, Dict, Any\n\nclass DashboardResponse(BaseModel):\n    today_doses: int\n    next_appointment: Any\n    unread_messages: int\n''',

    "app/api/prescriptions.py": '''from fastapi import APIRouter, Depends, HTTPException\nfrom sqlalchemy.ext.asyncio import AsyncSession\nfrom sqlalchemy import select\nfrom app.database import get_db\nfrom app.dependencies import get_current_user\nfrom app.models.user import User\nfrom app.models.patient import Patient\nfrom app.models.prescription import Prescription\nfrom app.schemas.prescription import PrescriptionResponse\nfrom typing import List\n\nrouter = APIRouter(prefix="/api/v1/patients/me/prescriptions", tags=["prescriptions"])\n\n@router.get("", response_model=List[PrescriptionResponse])\nasync def get_prescriptions(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):\n    result = await db.execute(select(Patient).where(Patient.user_id == current_user.id))\n    patient = result.scalar_one_or_none()\n    if not patient: raise HTTPException(status_code=404, detail="Patient not found")\n    prescriptions = await db.execute(select(Prescription).where(Prescription.patient_id == patient.id))\n    return prescriptions.scalars().all()\n''',

    "app/api/medications.py": '''from fastapi import APIRouter, Depends, HTTPException\nfrom sqlalchemy.ext.asyncio import AsyncSession\nfrom sqlalchemy import select\nfrom app.database import get_db\nfrom app.dependencies import get_current_user\nfrom app.models.user import User\nfrom app.models.patient import Patient\nfrom app.models.medication import PrescriptionItem\nfrom app.models.prescription import Prescription\nfrom app.schemas.medication import MedicationResponse\nfrom typing import List\n\nrouter = APIRouter(prefix="/api/v1/patients/me/medications", tags=["medications"])\n\n@router.get("", response_model=List[MedicationResponse])\nasync def get_medications(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):\n    # Simplified for demo\n    return []\n''',

    "app/api/doses.py": '''from fastapi import APIRouter, Depends, HTTPException\nfrom sqlalchemy.ext.asyncio import AsyncSession\nfrom sqlalchemy import select\nfrom app.database import get_db\nfrom app.dependencies import get_current_user\nfrom app.models.user import User\nfrom app.schemas.dose import DoseResponse\nfrom typing import List\n\nrouter = APIRouter(prefix="/api/v1/patients/me/doses", tags=["doses"])\n\n@router.get("/today", response_model=List[DoseResponse])\nasync def get_today_doses(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):\n    return []\n''',
    
    "tests/conftest.py": '''import pytest\nfrom httpx import AsyncClient\nfrom app.main import app\n\n@pytest.fixture\nasync def client():\n    async with AsyncClient(app=app, base_url="http://test") as ac:\n        yield ac\n''',

    "tests/test_auth.py": '''import pytest\nfrom httpx import AsyncClient\n\n@pytest.mark.asyncio\nasync def test_health(client: AsyncClient):\n    response = await client.get("/health")\n    assert response.status_code == 200\n'''
}

# Add __init__.py files for schemas and tests
files_to_create["app/schemas/__init__.py"] = ""
files_to_create["tests/__init__.py"] = ""

for relative_path, content in files_to_create.items():
    file_path = os.path.join(base_dir, relative_path.replace("/", os.sep))
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

print(f"Created {len(files_to_create)} additional files successfully.")
