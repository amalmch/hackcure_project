import pytest
import uuid
from httpx import AsyncClient
from app.config import settings

@pytest.mark.asyncio
async def test_full_system_e2e_flow(client: AsyncClient):
    # 1. Health check
    res = await client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    # 2. Login as patient
    login_res = await client.post(
        "/api/v1/auth/login",
        json={"email": "mohamed@example.com", "password": "Test123!@#"}
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 3. Patient Profile
    profile_res = await client.get("/api/v1/patients/me", headers=headers)
    assert profile_res.status_code == 200
    patient_id = profile_res.json()["id"]

    # 4. Dashboard
    dash_res = await client.get("/api/v1/patients/me/dashboard", headers=headers)
    assert dash_res.status_code == 200

    # 5. Active Prescriptions (Ordonnance)
    presc_res = await client.get("/api/v1/patients/me/prescriptions", headers=headers)
    assert presc_res.status_code == 200

    # 6. Treatment Summary (Rapport du medecin)
    summary_res = await client.get("/api/v1/patients/me/treatment-summary", headers=headers)
    assert summary_res.status_code == 200
    assert summary_res.json()["is_current"] is True

    # 7. Today Doses (Reminders schedule)
    doses_res = await client.get("/api/v1/patients/me/doses/today", headers=headers)
    assert doses_res.status_code == 200

    # 8. Dose history
    history_res = await client.get("/api/v1/patients/me/doses/history", headers=headers)
    assert history_res.status_code == 200

    # 9. n8n automation upload: Doctor Report draft
    auto_headers = {"X-Automation-Key": settings.AUTOMATION_API_KEY}
    report_payload = {
        "patient_id": patient_id,
        "diagnostic": "Bilan de sante semestriel - Statut stable",
        "objectifs_traitement": ["Maintien de la pression arterielle"],
        "precautions": ["Hydratation quotidienne"],
        "alertes": ["Cephalees"],
        "dates_suivi": ["2026-12-15"],
        "sport": {
            "recommande": ["Marche rapide 45 min", "Gymnastique douce"],
            "a_eviter": ["Haltérophilie"],
            "frequence": "4x par semaine",
            "intensite": "MODERATE",
            "duree": "45 min"
        },
        "nutrition": {
            "regime_type": "DASH / Mediterraneen",
            "a_privilegier": ["Legumes verts", "Poissons"],
            "a_limiter": ["Sel", "Plats industriels"],
            "hydratation_ml": 2200,
            "calories_cible": 2000
        },
        "resume_patient": "Votre etat est tres satisfaisant. Maintenez vos efforts."
    }
    r_draft = await client.post("/api/automation/report", json=report_payload, headers=auto_headers)
    assert r_draft.status_code == 200
    doc1_id = r_draft.json()["document_source_id"]

    # 10. n8n automation upload: Prescription draft
    p_num = f"RX-E2E-{uuid.uuid4().hex[:6].upper()}"
    presc_payload = {
        "patient_id": patient_id,
        "prescription_number": p_num,
        "diagnosis": "Bilan semestriel",
        "medicaments": [
            {
                "nom": "Amlodipine",
                "posologie": "5mg le matin",
                "forme": "TABLET",
                "frequence": "Daily",
                "heures_prises": ["08:00"],
                "duree_jours": 30,
                "quantite": 30
            }
        ]
    }
    p_draft = await client.post("/api/automation/prescription", json=presc_payload, headers=auto_headers)
    assert p_draft.status_code == 200
    doc2_id = p_draft.json()["document_source_id"]

    # 11. Retrieve drafts
    drafts_res = await client.get(f"/api/automation/drafts/{patient_id}", headers=auto_headers)
    assert drafts_res.status_code == 200
    assert len(drafts_res.json()) >= 2

    # 12. Apply drafts atomically
    apply_payload = {
        "document_source_ids": [doc1_id, doc2_id],
        "confirmed_by": "patient_e2e_tester"
    }
    apply_res = await client.post("/api/automation/apply", json=apply_payload, headers=auto_headers)
    assert apply_res.status_code == 200
    applied_data = apply_res.json()
    assert applied_data["success"] is True
    assert applied_data["doses_generated"] > 0
    assert applied_data["sport_plans_created"] > 0
    assert applied_data["nutrition_plans_created"] > 0
