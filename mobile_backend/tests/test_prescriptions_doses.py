import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_get_dashboard(client: AsyncClient, auth_headers):
    headers = await auth_headers(client)
    response = await client.get("/api/v1/patients/me/dashboard", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "today_doses" in data
    assert "adherence" in data
    assert data["active_prescriptions_count"] >= 1
    assert data["adherence"]["overall_percentage"] > 0
    daily = data["adherence"]["daily"]
    assert daily["total"] == len(data["today_doses"])
    assert sum(daily[key] for key in ("taken_on_time", "taken_late", "missed", "pending")) == daily["total"]
    status_counts = {
        "taken_on_time": sum(d["status"] == "TAKEN_ON_TIME" for d in data["today_doses"]),
        "taken_late": sum(d["status"] == "TAKEN_LATE" for d in data["today_doses"]),
        "missed": sum(d["status"] == "MISSED" for d in data["today_doses"]),
        "pending": sum(d["status"] in {"SCHEDULED", "DUE", "REMINDING"} for d in data["today_doses"]),
    }
    assert {key: daily[key] for key in status_counts} == status_counts

@pytest.mark.asyncio
async def test_get_prescriptions(client: AsyncClient, auth_headers):
    headers = await auth_headers(client)
    response = await client.get("/api/v1/patients/me/prescriptions", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    presc = data[0]
    assert "doctor" in presc
    assert "items" in presc
    assert len(presc["items"]) >= 1

@pytest.mark.asyncio
async def test_get_today_doses_and_take_dose(client: AsyncClient, auth_headers):
    headers = await auth_headers(client)
    # Get today doses
    response = await client.get("/api/v1/patients/me/doses/today", headers=headers)
    assert response.status_code == 200
    doses = response.json()

    # If no doses for today, get active prescription items and insert a test dose
    if len(doses) == 0:
        from app.database import AsyncSessionLocal
        from app.models.dose import MedicationDose, DoseStatus
        from app.models.medication import PrescriptionItem
        from app.models.patient import Patient
        from sqlalchemy import select
        from datetime import date, time
        import uuid

        async with AsyncSessionLocal() as session:
            patient_res = await session.execute(select(Patient))
            patient = patient_res.scalars().first()
            item_res = await session.execute(select(PrescriptionItem))
            item = item_res.scalars().first()
            if patient and item:
                new_dose = MedicationDose(
                    id=uuid.uuid4(),
                    prescription_item_id=item.id,
                    patient_id=patient.id,
                    scheduled_date=date.today(),
                    scheduled_time=time(13, 0),
                    status=DoseStatus.DUE
                )
                session.add(new_dose)
                await session.commit()
        response = await client.get("/api/v1/patients/me/doses/today", headers=headers)
        doses = response.json()

    assert len(doses) >= 1

    # Find a scheduled/due dose and take it
    due_dose = next((d for d in doses if d["status"] in ["DUE", "SCHEDULED"]), None)
    if not due_dose:
        due_dose = doses[0]

    take_res = await client.post(
        f"/api/v1/medication-doses/{due_dose['id']}/take",
        headers=headers,
        json={"taken_at": "2026-10-10T13:02:00"}
    )
    assert take_res.status_code == 200
    assert take_res.json()["status"] in ["TAKEN_ON_TIME", "TAKEN_LATE"]
    assert take_res.json()["taken_at"] is not None


@pytest.mark.asyncio
async def test_take_dose_accepts_local_timestamp_and_scopes_idempotency(client: AsyncClient, auth_headers):
    import uuid
    from datetime import date, datetime
    from zoneinfo import ZoneInfo
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.dose import MedicationDose, DoseStatus
    from app.models.medication import PrescriptionItem
    from app.models.patient import Patient
    from app.models.user import User

    async with AsyncSessionLocal() as session:
        user_result = await session.execute(select(User).where(User.email == "mohamed@example.com"))
        user_a = user_result.scalar_one()
        patient_result = await session.execute(select(Patient).where(Patient.user_id == user_a.id))
        patient_a = patient_result.scalar_one()
        item_result = await session.execute(select(PrescriptionItem).limit(1))
        item = item_result.scalar_one()

        scheduled_local = datetime.now(ZoneInfo("Africa/Tunis")).replace(second=0, microsecond=0)
        dose_id = uuid.uuid4()
        dose = MedicationDose(
            id=dose_id,
            prescription_item_id=item.id,
            patient_id=patient_a.id,
            scheduled_date=scheduled_local.date(),
            scheduled_time=scheduled_local.time().replace(tzinfo=None),
            status=DoseStatus.DUE,
        )
        session.add(dose)
        user_b = User(
            id=uuid.uuid4(),
            email=f"dose-isolation-{uuid.uuid4()}@example.com",
            password_hash="unused-test-password-hash",
            role="PATIENT",
            is_active=True,
            is_verified=True,
        )
        session.add(user_b)
        await session.flush()
        patient_b = Patient(user_id=user_b.id, first_name="Other", last_name="Patient")
        session.add(patient_b)
        await session.commit()

    from app.utils.security import create_access_token
    patient_a_headers = {"Authorization": f"Bearer {create_access_token({'sub': str(user_a.id)})}"}

    take_response = await client.post(
        f"/api/v1/medication-doses/{dose_id}/take",
        headers=patient_a_headers,
        json={"idempotency_key": str(dose_id), "taken_at": scheduled_local.isoformat()},
    )
    assert take_response.status_code == 200
    assert take_response.json()["status"] == "TAKEN_ON_TIME"
    assert take_response.json()["taken_at"] is not None

    patient_b_headers = {"Authorization": f"Bearer {create_access_token({'sub': str(user_b.id)})}"}

    own_doses_response = await client.get("/api/v1/patients/me/doses/today", headers=patient_b_headers)
    assert own_doses_response.status_code == 200
    assert all(item["id"] != str(dose_id) for item in own_doses_response.json())

    replay_response = await client.post(
        f"/api/v1/medication-doses/{dose_id}/take",
        headers=patient_b_headers,
        json={"idempotency_key": str(dose_id)},
    )
    assert replay_response.status_code == 404
