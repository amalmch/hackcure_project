import pytest
from httpx import AsyncClient
import uuid

@pytest.mark.asyncio
async def test_automation_report_draft_and_apply(client: AsyncClient, auth_headers):
    headers = await auth_headers(client)
    # 1. Get current patient ID
    profile_res = await client.get("/api/v1/patients/me", headers=headers)
    assert profile_res.status_code == 200
    patient_id = profile_res.json()["id"]

    automation_headers = {
        "X-Automation-Key": "hackcure-automation-dev-key-2026",
        "Content-Type": "application/json"
    }

    # 2. Stage a doctor report extraction
    report_payload = {
        "patient_id": patient_id,
        "motif_consultation": "Contrôle semestriel cardiologique et tension artérielle",
        "diagnostic": "Hypertension artérielle stade 1 bien contrôlée, dyslipidémie modérée",
        "conclusion": "Poursuite du traitement cardiovasculaire avec adaptation de la marche quotidienne.",
        "objectifs_traitement": [
            "Maintenir une pression artérielle < 130/80 mmHg",
            "Réduire le cholestérol LDL < 1.0 g/L"
        ],
        "precautions": [
            "Surveiller la tension artérielle 1 fois par semaine le matin",
            "Consulter en cas d'étourdissements ou de douleurs thoraciques"
        ],
        "alertes": [
            "Pression systolique > 180 mmHg = urgence médicale",
            "Ne jamais doubler une dose oubliée"
        ],
        "dates_suivi": ["2026-11-15"],
        "sport": {
            "recommande": ["Marche rapide à 5 km/h", "Natation modérée"],
            "a_eviter": ["Haltérophilie lourde", "Sports de combat violents"],
            "frequence": "4 à 5 fois par semaine",
            "intensite": "MODERATE",
            "duree": "30 à 45 minutes",
            "restrictions": ["Garder la fréquence cardiaque en dessous de 135 bpm"],
            "jours": ["Lundi", "Mercredi", "Vendredi", "Dimanche"]
        },
        "nutrition": {
            "a_privilegier": [
                "Légumes verts à feuilles (épinards, roquette)",
                "Poissons gras riches en oméga-3 (saumon, sardines)",
                "Huile d'olive extra vierge"
            ],
            "a_limiter": [
                "Sel de table ajouté (< 2g sodium/jour)",
                "Charcuteries et viandes transformées",
                "Boissons sucrées et sodas"
            ],
            "conseils": "Régime méditerranéen hypocalorique adapté à l'hypertension.",
            "regime_type": "DASH / Méditerranéen",
            "hydratation_ml": 2200,
            "calories_cible": 2000
        },
        "medicaments": [
            {
                "nom": "Amlodipine Besylate",
                "principe_actif": "Amlodipine",
                "posologie": "5 mg",
                "forme": "TABLET",
                "frequence": "1 fois par jour",
                "heures_prises": ["08:00"],
                "duree_jours": 90,
                "confidence": 0.98
            }
        ],
        "resume_patient": "Votre tension est bien stabilisée. Continuez à marcher 30 minutes 4 fois par semaine et réduisez le sel. Prochain bilan dans un mois.",
        "confidence_scores": {
            "diagnostic": 0.95,
            "medicaments": 0.98,
            "sport": 0.90,
            "nutrition": 0.92,
            "global": 0.94
        }
    }

    rep_res = await client.post("/api/automation/report", headers=automation_headers, json=report_payload)
    assert rep_res.status_code == 200
    report_draft = rep_res.json()
    assert report_draft["status"] == "DRAFT"
    report_doc_id = report_draft["document_source_id"]

    # 3. Stage a prescription extraction
    prescription_payload = {
        "patient_id": patient_id,
        "prescription_number": "RX-AUTOMATED-2026-001",
        "doctor_name": "Dr. Ahmed Ben Ali",
        "diagnosis": "Hypertension artérielle & Dyslipidémie",
        "notes": "Prendre scrupuleusement aux heures indiquées avec un verre d'eau.",
        "date_debut": "2026-10-10",
        "date_fin": "2027-01-10",
        "medicaments": [
            {
                "nom": "Amlodipine Besylate",
                "principe_actif": "Amlodipine",
                "posologie": "5 mg",
                "forme": "TABLET",
                "frequence": "Une fois par jour le matin",
                "heures_prises": ["08:00"],
                "duree_jours": 90,
                "instructions": "1 comprimé le matin au réveil avec de l'eau.",
                "avant_repas": False,
                "quantite": 90,
                "confidence": 0.99
            },
            {
                "nom": "Atorvastatine Calcium",
                "principe_actif": "Atorvastatine",
                "posologie": "20 mg",
                "forme": "TABLET",
                "frequence": "Une fois par jour le soir",
                "heures_prises": ["20:00"],
                "duree_jours": 90,
                "instructions": "1 comprimé le soir au coucher.",
                "avant_repas": False,
                "quantite": 90,
                "confidence": 0.95
            }
        ],
        "confidence_scores": {
            "medicaments": 0.97,
            "dates": 0.95,
            "global": 0.96
        }
    }

    presc_res = await client.post("/api/automation/prescription", headers=automation_headers, json=prescription_payload)
    assert presc_res.status_code == 200
    presc_draft = presc_res.json()
    assert presc_draft["status"] == "DRAFT"
    presc_doc_id = presc_draft["document_source_id"]

    # 4. Check drafts listing endpoint
    drafts_res = await client.get(f"/api/automation/drafts/{patient_id}", headers=automation_headers)
    assert drafts_res.status_code == 200
    drafts = drafts_res.json()
    assert len(drafts) >= 2

    # 5. Apply both drafts atomically
    apply_res = await client.post(
        "/api/automation/apply",
        headers=automation_headers,
        json={
            "document_source_ids": [report_doc_id, presc_doc_id],
            "confirmed_by": "patient"
        }
    )
    assert apply_res.status_code == 200
    apply_data = apply_res.json()
    assert apply_data["success"] is True
    assert apply_data["prescription_id"] is not None
    assert apply_data["treatment_summary_id"] is not None
    assert apply_data["doses_generated"] > 0
    assert apply_data["sport_plans_created"] >= 1
    assert apply_data["nutrition_plans_created"] >= 1

    # 6. Verify Treatment Summary is now accessible by the patient
    summary_res = await client.get("/api/v1/patients/me/treatment-summary", headers=headers)
    assert summary_res.status_code == 200
    summary = summary_res.json()
    assert summary["diagnosis"] == "Hypertension artérielle stade 1 bien contrôlée, dyslipidémie modérée"
    assert "Maintenir une pression artérielle < 130/80 mmHg" in summary["treatment_goals"]
    assert "Ne jamais doubler une dose oubliée" in summary["warnings"]
    assert summary["patient_summary"] is not None

    # 7. Verify sport plan updated
    sport_res = await client.get("/api/v1/patients/me/sport/plans", headers=headers)
    assert sport_res.status_code == 200
    assert len(sport_res.json()) >= 1

    # 8. Verify nutrition plan updated
    nutrition_res = await client.get("/api/v1/patients/me/nutrition", headers=headers)
    assert nutrition_res.status_code == 200
    assert len(nutrition_res.json()) >= 1
