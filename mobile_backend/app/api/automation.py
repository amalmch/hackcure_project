import uuid
from datetime import datetime, timedelta, date, timezone
from typing import List, Optional

TUNIS_TZ = timezone(timedelta(hours=1))  # Africa/Tunis (UTC+1 year-round)
from fastapi import APIRouter, Depends, HTTPException, Security, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, update
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.config import settings

from app.models.document_source import DocumentSource, DocumentType, DocumentStatus
from app.models.treatment_summary import TreatmentSummary
from app.models.audit_log import AuditLog
from app.models.prescription import Prescription, PrescriptionStatus
from app.models.medication import PrescriptionItem, MedicationForm
from app.models.dose import MedicationDose, DoseStatus
from app.models.sport import SportPlan, SportActivity, ActivityType, Intensity, PlanStatus, ActivityStatus
from app.models.nutrition import NutritionPlan, NutritionPlanStatus
from app.models.patient import Patient

from app.schemas.automation import (
    ReportExtractionPayload,
    PrescriptionExtractionPayload,
    DraftResponse,
    ApplyPayload,
    ApplyResult,
)

router = APIRouter(prefix="/api/automation", tags=["automation"])

async def verify_api_key(x_automation_key: str = Header(...)):
    if x_automation_key != settings.AUTOMATION_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid automation API key")
    return x_automation_key

@router.post("/report", response_model=DraftResponse)
async def create_report_draft(
    payload: ReportExtractionPayload,
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(verify_api_key)
):
    # Check if patient exists
    patient_res = await db.execute(select(Patient).where(Patient.id == payload.patient_id))
    if not patient_res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Patient not found")

    doc = DocumentSource(
        id=payload.document_source_id or uuid.uuid4(),
        patient_id=payload.patient_id,
        document_type=DocumentType.DOCTOR_REPORT,
        status=DocumentStatus.DRAFT,
        extracted_data=payload.model_dump(mode="json"),
        confidence_scores=payload.confidence_scores
    )
    db.add(doc)

    summary = TreatmentSummary(
        patient_id=payload.patient_id,
        document_source_id=doc.id,
        diagnosis=payload.diagnostic,
        treatment_goals=payload.objectifs_traitement,
        precautions=payload.precautions,
        warnings=payload.alertes,
        follow_up_dates=payload.dates_suivi,
        consultation_reason=payload.motif_consultation,
        doctor_conclusion=payload.conclusion,
        patient_summary=payload.resume_patient,
        sport_recommendations=payload.sport.model_dump(mode="json") if payload.sport else None,
        nutrition_recommendations=payload.nutrition.model_dump(mode="json") if payload.nutrition else None,
        is_current=False # Still a draft
    )
    db.add(summary)
    
    await db.commit()
    await db.refresh(doc)

    low_conf = []
    if payload.confidence_scores:
        for k, v in payload.confidence_scores.items():
            if isinstance(v, (int, float)) and v < 0.7:
                low_conf.append(k)

    return DraftResponse(
        document_source_id=doc.id,
        document_type=doc.document_type,
        status=doc.status,
        version=doc.version,
        extracted_data=doc.extracted_data,
        confidence_scores=doc.confidence_scores,
        low_confidence_fields=low_conf,
        created_at=doc.created_at
    )

@router.post("/prescription", response_model=DraftResponse)
async def create_prescription_draft(
    payload: PrescriptionExtractionPayload,
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(verify_api_key)
):
    # Check if patient exists
    patient_res = await db.execute(select(Patient).where(Patient.id == payload.patient_id))
    if not patient_res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Patient not found")

    doc = DocumentSource(
        id=payload.document_source_id or uuid.uuid4(),
        patient_id=payload.patient_id,
        document_type=DocumentType.PRESCRIPTION,
        status=DocumentStatus.DRAFT,
        extracted_data=payload.model_dump(mode="json"),
        confidence_scores=payload.confidence_scores
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    low_conf = []
    if payload.confidence_scores:
        for k, v in payload.confidence_scores.items():
            if isinstance(v, (int, float)) and v < 0.7:
                low_conf.append(k)

    return DraftResponse(
        document_source_id=doc.id,
        document_type=doc.document_type,
        status=doc.status,
        version=doc.version,
        extracted_data=doc.extracted_data,
        confidence_scores=doc.confidence_scores,
        low_confidence_fields=low_conf,
        created_at=doc.created_at
    )

@router.get("/drafts/{patient_id}", response_model=List[DraftResponse])
async def get_patient_drafts(
    patient_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(verify_api_key)
):
    res = await db.execute(
        select(DocumentSource).where(
            and_(
                DocumentSource.patient_id == patient_id,
                DocumentSource.status == DocumentStatus.DRAFT
            )
        )
    )
    docs = res.scalars().all()
    
    responses = []
    for doc in docs:
        low_conf = []
        if doc.confidence_scores:
            for k, v in doc.confidence_scores.items():
                if isinstance(v, (int, float)) and v < 0.7:
                    low_conf.append(k)
                    
        responses.append(DraftResponse(
            document_source_id=doc.id,
            document_type=doc.document_type.value,
            status=doc.status.value,
            version=doc.version,
            extracted_data=doc.extracted_data,
            confidence_scores=doc.confidence_scores,
            low_confidence_fields=low_conf,
            created_at=doc.created_at
        ))
    return responses

async def execute_apply_drafts(payload: ApplyPayload, db: AsyncSession) -> ApplyResult:
    res = ApplyResult(success=True)
    now_tunis = datetime.now(TUNIS_TZ)
    today = now_tunis.date()
    
    for doc_id in payload.document_source_ids:
        doc_res = await db.execute(select(DocumentSource).where(DocumentSource.id == doc_id))
        doc = doc_res.scalar_one_or_none()
        if not doc or doc.status != DocumentStatus.DRAFT:
            res.warnings.append(f"Document {doc_id} not found or not DRAFT")
            continue

        doc.status = DocumentStatus.APPLIED
        doc.applied_at = datetime.utcnow()

        if doc.document_type == DocumentType.DOCTOR_REPORT:
            # Archive old
            await db.execute(
                update(TreatmentSummary)
                .where(and_(TreatmentSummary.patient_id == doc.patient_id, TreatmentSummary.is_current == True))
                .values(is_current=False)
            )
            
            # Make draft current
            draft_sum_res = await db.execute(
                select(TreatmentSummary).where(TreatmentSummary.document_source_id == doc.id)
            )
            draft_sum = draft_sum_res.scalar_one_or_none()
            if draft_sum:
                draft_sum.is_current = True
                res.treatment_summary_id = draft_sum.id
            
            # Create AuditLog
            audit = AuditLog(
                patient_id=doc.patient_id,
                document_source_id=doc.id,
                action="REPORT_EXTRACTED",
                entity_type="TreatmentSummary",
                entity_id=draft_sum.id if draft_sum else None,
                performed_by=payload.confirmed_by
            )
            db.add(audit)
            await db.flush()
            res.audit_log_ids.append(audit.id)
            
            # Sport & Nutrition handling
            data = doc.extracted_data
            if data and data.get("sport"):
                sport_data = data["sport"]
                reco = sport_data.get("recommande", [])
                act_name = reco[0] if (reco and isinstance(reco, list)) else "Marche adaptée"
                s_plan = SportPlan(
                    patient_id=doc.patient_id,
                    activity_name=act_name,
                    activity_type=ActivityType.WALKING,
                    duration_minutes=30,
                    intensity=Intensity.MODERATE,
                    frequency_per_week=4,
                    scheduled_days=sport_data.get("jours", ["Lundi", "Mercredi", "Vendredi", "Dimanche"]),
                    instructions="\n".join(sport_data.get("restrictions", [])) or "Activité modérée selon avis médical",
                    doctor_notes=sport_data.get("frequence"),
                    status=PlanStatus.ACTIVE
                )
                db.add(s_plan)
                res.sport_plans_created += 1
            if data and data.get("nutrition"):
                nut_data = data["nutrition"]
                n_plan = NutritionPlan(
                    patient_id=doc.patient_id,
                    plan_type=nut_data.get("regime_type", "DASH / Méditerranéen"),
                    recommended_foods=nut_data.get("a_privilegier", []),
                    foods_to_avoid=nut_data.get("a_limiter", []),
                    meal_recommendations=nut_data.get("repas"),
                    hydration_ml_daily=nut_data.get("hydratation_ml", 2000),
                    calories_target=nut_data.get("calories_cible", 2000),
                    doctor_notes=nut_data.get("conseils"),
                    status=NutritionPlanStatus.ACTIVE
                )
                db.add(n_plan)
                res.nutrition_plans_created += 1

        elif doc.document_type == DocumentType.PRESCRIPTION:
            data = doc.extracted_data
            
            # Archive active prescription
            await db.execute(
                update(Prescription)
                .where(and_(Prescription.patient_id == doc.patient_id, Prescription.status == PrescriptionStatus.ACTIVE))
                .values(status=PrescriptionStatus.COMPLETED, is_current=False)
            )

            start_dt = date.fromisoformat(data.get("date_debut")) if data.get("date_debut") else today
            end_dt = date.fromisoformat(data.get("date_fin")) if data.get("date_fin") else (start_dt + timedelta(days=30))
            
            p_num = data.get("prescription_number")
            if p_num:
                existing_p = await db.execute(select(Prescription).where(Prescription.prescription_number == p_num))
                if existing_p.scalar_one_or_none():
                    p_num = f"{p_num}-{uuid.uuid4().hex[:4].upper()}"
            else:
                p_num = f"RX-{uuid.uuid4().hex[:8].upper()}"

            presc = Prescription(
                patient_id=doc.patient_id,
                prescription_number=p_num,
                diagnosis=data.get("diagnosis"),
                notes=data.get("notes"),
                start_date=start_dt,
                end_date=end_dt,
                status=PrescriptionStatus.ACTIVE,
                is_current=True,
                version=1
            )
            db.add(presc)
            await db.flush()
            res.prescription_id = presc.id

            audit = AuditLog(
                patient_id=doc.patient_id,
                document_source_id=doc.id,
                action="PRESCRIPTION_APPLIED",
                entity_type="Prescription",
                entity_id=presc.id,
                performed_by=payload.confirmed_by
            )
            db.add(audit)
            await db.flush()
            res.audit_log_ids.append(audit.id)

            # Cancel old pending doses
            old_doses = await db.execute(
                select(MedicationDose)
                .where(and_(MedicationDose.patient_id == doc.patient_id, MedicationDose.status == DoseStatus.SCHEDULED))
            )
            for d in old_doses.scalars():
                d.status = DoseStatus.CANCELLED
                res.old_reminders_cancelled += 1
                
            audit2 = AuditLog(
                patient_id=doc.patient_id,
                document_source_id=doc.id,
                action="REMINDERS_CLEARED",
                performed_by=payload.confirmed_by
            )
            db.add(audit2)

            # Generate new doses
            medicaments = data.get("medicaments", [])
            for med in medicaments:
                form_val = None
                if med.get("forme"):
                    try:
                        form_val = MedicationForm(med["forme"].upper())
                    except:
                        pass
                        
                d_jours = med.get("duree_jours")
                m_end_dt = (start_dt + timedelta(days=d_jours)) if d_jours else end_dt
                
                item = PrescriptionItem(
                    prescription_id=presc.id,
                    medication_name=med["nom"],
                    active_ingredient=med.get("principe_actif"),
                    dosage=med["posologie"],
                    form=form_val,
                    frequency=med.get("frequence", "Daily"),
                    scheduled_times=med.get("heures_prises", []),
                    duration_days=d_jours,
                    start_date=start_dt,
                    end_date=m_end_dt,
                    instructions=med.get("instructions"),
                    before_food=med.get("avant_repas"),
                    quantity_prescribed=med.get("quantite")
                )
                db.add(item)
                await db.flush()

                # Generate doses
                curr_date = start_dt
                while curr_date <= m_end_dt:
                    for time_str in med.get("heures_prises", []):
                        t_obj = datetime.strptime(time_str, "%H:%M").time()
                        d_status = DoseStatus.SCHEDULED
                        if curr_date == today:
                            if t_obj <= now_tunis.time():
                                d_status = DoseStatus.DUE
                        elif curr_date < today:
                            d_status = DoseStatus.MISSED

                        dose = MedicationDose(
                            patient_id=doc.patient_id,
                            prescription_item_id=item.id,
                            scheduled_date=curr_date,
                            scheduled_time=t_obj,
                            status=d_status
                        )
                        db.add(dose)
                        res.doses_generated += 1
                    curr_date += timedelta(days=1)
                    
            audit3 = AuditLog(
                patient_id=doc.patient_id,
                document_source_id=doc.id,
                action="DOSES_REGENERATED",
                entity_type="Prescription",
                entity_id=presc.id,
                performed_by=payload.confirmed_by
            )
            db.add(audit3)

    await db.commit()
    return res

@router.post("/apply", response_model=ApplyResult)
async def apply_drafts(
    payload: ApplyPayload,
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(verify_api_key)
):
    return await execute_apply_drafts(payload, db)

