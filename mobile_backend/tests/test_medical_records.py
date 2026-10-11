from datetime import date
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import delete

from app.database import AsyncSessionLocal
from app.models.medical_record import MedicalRecord, RecordType
from app.models.patient import Patient
from app.models.user import User


@pytest.mark.asyncio
async def test_medical_dossier_is_scoped_to_authenticated_patient(client: AsyncClient):
    first_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "mohamed@example.com", "password": "Test123!@#"},
    )
    assert first_login.status_code == 200
    first_headers = {"Authorization": f"Bearer {first_login.json()['access_token']}"}
    first_profile = await client.get("/api/v1/patients/me", headers=first_headers)
    first_patient_id = UUID(first_profile.json()["id"])

    unique = uuid4().hex
    second_email = f"dossier-{unique}@example.com"
    second_password = "PatientTest123!"
    second_register = await client.post(
        "/api/v1/auth/register",
        json={
            "email": second_email,
            "password": second_password,
            "first_name": "Test",
            "last_name": "Patient",
        },
    )
    assert second_register.status_code == 200
    second_user_id = UUID(second_register.json()["id"])
    second_login = await client.post(
        "/api/v1/auth/login",
        json={"email": second_email, "password": second_password},
    )
    assert second_login.status_code == 200
    second_headers = {"Authorization": f"Bearer {second_login.json()['access_token']}"}
    second_profile = await client.get("/api/v1/patients/me", headers=second_headers)
    second_patient_id = UUID(second_profile.json()["id"])

    first_record_id, second_record_id = uuid4(), uuid4()
    try:
        async with AsyncSessionLocal() as session:
            session.add_all([
                MedicalRecord(
                    id=first_record_id,
                    patient_id=first_patient_id,
                    record_type=RecordType.DOCUMENT,
                    title="First patient's test dossier item",
                    record_date=date.today(),
                ),
                MedicalRecord(
                    id=second_record_id,
                    patient_id=second_patient_id,
                    record_type=RecordType.DOCUMENT,
                    title="Second patient's test dossier item",
                    record_date=date.today(),
                ),
            ])
            await session.commit()

        first_records = await client.get("/api/v1/medical-records", headers=first_headers)
        second_records = await client.get("/api/v1/medical-records", headers=second_headers)
        assert first_records.status_code == 200
        assert second_records.status_code == 200
        assert str(first_record_id) in {record["id"] for record in first_records.json()}
        assert str(second_record_id) not in {record["id"] for record in first_records.json()}
        assert str(second_record_id) in {record["id"] for record in second_records.json()}
        assert str(first_record_id) not in {record["id"] for record in second_records.json()}

        cross_patient_detail = await client.get(
            f"/api/v1/medical-records/{first_record_id}", headers=second_headers
        )
        assert cross_patient_detail.status_code == 404
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(MedicalRecord).where(MedicalRecord.id.in_([first_record_id, second_record_id]))
            )
            await session.execute(delete(Patient).where(Patient.user_id == second_user_id))
            await session.execute(delete(User).where(User.id == second_user_id))
            await session.commit()
