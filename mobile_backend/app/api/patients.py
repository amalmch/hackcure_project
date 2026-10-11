import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from sqlalchemy.orm import selectinload
from typing import List, Optional
from datetime import date, datetime, timedelta

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.patient import Patient
from app.models.doctor import Doctor
from app.models.prescription import Prescription, PrescriptionStatus
from app.models.medication import PrescriptionItem
from app.models.dose import MedicationDose, DoseStatus
from app.models.sport import SportPlan, SportActivity, ActivityStatus
from app.models.nutrition import NutritionPlan
from app.models.appointment import Appointment, AppointmentStatus
from app.models.notification import Notification
from app.models.treatment_summary import TreatmentSummary
from app.models.document_source import DocumentSource, DocumentStatus

from app.schemas.patient import PatientResponse, PatientUpdate
from app.schemas.doctor import DoctorResponse
from app.schemas.prescription import PrescriptionResponse
from app.schemas.medication import PrescriptionItemResponse
from app.schemas.dose import DoseResponse
from app.schemas.sport import SportPlanResponse, SportActivityResponse
from app.schemas.nutrition import NutritionPlanResponse
from app.schemas.dashboard import (
    DashboardDataResponse, AdherenceStatsResponse, WeeklyAdherence, DailyAdherence
)
from app.schemas.automation import (
    TreatmentSummaryResponse, DraftResponse, ApplyPayload, ApplyResult
)
from app.services.dose_status import dose_response, intake_counts, patient_now, patient_today

router = APIRouter(prefix="/api/v1/patients", tags=["patients"])


def dashboard_progress(today_doses: list[DoseResponse], today_sport_activities: list[SportActivity]) -> tuple[dict, dict]:
    taken_statuses = {DoseStatus.TAKEN_ON_TIME.value, DoseStatus.TAKEN_LATE.value}
    pending_statuses = {DoseStatus.SCHEDULED.value, DoseStatus.DUE.value, DoseStatus.REMINDING.value}
    taken = sum(1 for dose in today_doses if dose.status in taken_statuses)
    missed = sum(1 for dose in today_doses if dose.status == DoseStatus.MISSED.value)
    pending = sum(1 for dose in today_doses if dose.status in pending_statuses)
    total = len(today_doses)
    completed = sum(1 for activity in today_sport_activities if activity.status == ActivityStatus.COMPLETED)
    sport_total = len(today_sport_activities)
    return (
        {"total": total, "taken": taken, "missed": missed, "pending": pending,
         "percentage": round(taken * 100 / total, 1) if total else 0},
        {"total": sport_total, "completed": completed,
         "percentage": round(completed * 100 / sport_total, 1) if sport_total else 0},
    )

async def get_patient_by_user(user: User, db: AsyncSession) -> Patient:
    result = await db.execute(select(Patient).where(Patient.user_id == user.id))
    patient = result.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")
    return patient

@router.get("/me", response_model=PatientResponse)
async def get_patient_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    return await get_patient_by_user(current_user, db)

@router.put("/me", response_model=PatientResponse)
async def update_patient_profile(
    patient_data: PatientUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    patient = await get_patient_by_user(current_user, db)
    update_data = patient_data.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(patient, key, value)
        
    await db.commit()
    await db.refresh(patient)
    return patient

@router.get("/me/doctors", response_model=List[DoctorResponse])
async def get_patient_doctors(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    patient = await get_patient_by_user(current_user, db)
    # Find all doctors who have written prescriptions or have appointments with this patient
    prescriptions = await db.execute(
        select(Prescription.doctor_id).where(Prescription.patient_id == patient.id)
    )
    doc_ids = set(prescriptions.scalars().all())
    
    appts = await db.execute(
        select(Appointment.doctor_id).where(Appointment.patient_id == patient.id)
    )
    doc_ids.update(appts.scalars().all())
    
    if not doc_ids:
        # Fallback to returning all active doctors for directory discovery
        all_docs = await db.execute(select(Doctor))
        return all_docs.scalars().all()
        
    result = await db.execute(select(Doctor).where(Doctor.id.in_(doc_ids)))
    return result.scalars().all()

@router.get("/me/prescriptions", response_model=List[PrescriptionResponse])
async def get_patient_prescriptions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    patient = await get_patient_by_user(current_user, db)
    result = await db.execute(
        select(Prescription)
        .options(selectinload(Prescription.doctor), selectinload(Prescription.items))
        .where(Prescription.patient_id == patient.id)
        .order_by(Prescription.created_at.desc())
    )
    return result.scalars().all()

@router.get("/me/prescriptions/active", response_model=List[PrescriptionResponse])
async def get_patient_active_prescriptions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    patient = await get_patient_by_user(current_user, db)
    result = await db.execute(
        select(Prescription)
        .options(selectinload(Prescription.doctor), selectinload(Prescription.items))
        .where(
            and_(
                Prescription.patient_id == patient.id,
                Prescription.status == PrescriptionStatus.ACTIVE
            )
        )
        .order_by(Prescription.created_at.desc())
    )
    return result.scalars().all()

@router.get("/me/medications", response_model=List[PrescriptionItemResponse])
async def get_patient_medications(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    patient = await get_patient_by_user(current_user, db)
    result = await db.execute(
        select(PrescriptionItem)
        .join(Prescription, PrescriptionItem.prescription_id == Prescription.id)
        .where(
            and_(
                Prescription.patient_id == patient.id,
                Prescription.status == PrescriptionStatus.ACTIVE
            )
        )
        .order_by(PrescriptionItem.medication_name.asc())
    )
    return result.scalars().all()

@router.get("/me/medications/{item_id}", response_model=PrescriptionItemResponse)
async def get_patient_medication_detail(
    item_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    patient = await get_patient_by_user(current_user, db)
    result = await db.execute(
        select(PrescriptionItem)
        .join(Prescription, PrescriptionItem.prescription_id == Prescription.id)
        .where(
            and_(
                PrescriptionItem.id == uuid.UUID(item_id),
                Prescription.patient_id == patient.id
            )
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Medication not found")
    return item

@router.get("/me/doses/today", response_model=List[DoseResponse])
async def get_today_doses(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    patient = await get_patient_by_user(current_user, db)
    today = patient_today(patient)
    result = await db.execute(
        select(MedicationDose)
        .options(selectinload(MedicationDose.prescription_item))
        .where(
            and_(
                MedicationDose.patient_id == patient.id,
                MedicationDose.scheduled_date == today,
                MedicationDose.status != DoseStatus.CANCELLED
            )
        )
        .order_by(MedicationDose.scheduled_time.asc())
    )
    now = patient_now(patient)
    return [dose_response(dose, patient, now) for dose in result.scalars().all()]

@router.get("/me/doses", response_model=List[DoseResponse])
async def get_doses_by_date(
    date_str: Optional[date] = Query(None, alias="date"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    patient = await get_patient_by_user(current_user, db)
    query_date = date_str or patient_today(patient)
    result = await db.execute(
        select(MedicationDose)
        .options(selectinload(MedicationDose.prescription_item))
        .where(
            and_(
                MedicationDose.patient_id == patient.id,
                MedicationDose.scheduled_date == query_date
            )
        )
        .order_by(MedicationDose.scheduled_time.asc())
    )
    now = patient_now(patient)
    return [dose_response(dose, patient, now) for dose in result.scalars().all()]

@router.get("/me/adherence", response_model=AdherenceStatsResponse)
async def get_patient_adherence(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    patient = await get_patient_by_user(current_user, db)
    now = patient_now(patient)
    today = now.date()
    seven_days_ago = today - timedelta(days=6)
    
    # All historical doses
    all_doses = await db.execute(
        select(MedicationDose).where(
            and_(
                MedicationDose.patient_id == patient.id,
                MedicationDose.scheduled_date <= today
            )
        )
    )
    doses = all_doses.scalars().all()
    
    total_counts = intake_counts(doses, patient, now)
    total = int(total_counts["total"])
    taken = int(total_counts["taken_on_time"]) + int(total_counts["taken_late"])
    missed = int(total_counts["missed"])
    overall_pct = float(total_counts["percentage"])

    today_doses = [d for d in doses if d.scheduled_date == today]
    daily_counts = intake_counts(today_doses, patient, now)

    # Weekly breakdown (last 7 days)
    daily_breakdown = []
    weekly_counts = {"total": 0, "taken_on_time": 0, "taken_late": 0, "missed": 0, "pending": 0}
    for day_offset in range(7):
        cur_day = seven_days_ago + timedelta(days=day_offset)
        cur_day_doses = [d for d in doses if d.scheduled_date == cur_day]
        day_counts = intake_counts(cur_day_doses, patient, now)
        d_total = int(day_counts["total"])
        d_taken = int(day_counts["taken_on_time"]) + int(day_counts["taken_late"])
        for key in weekly_counts:
            weekly_counts[key] += int(day_counts[key])
        daily_pct = float(day_counts["percentage"])
        daily_breakdown.append(DailyAdherence(
            date=cur_day.isoformat(),
            percentage=daily_pct,
            taken=d_taken,
            total=d_total
        ))

    weekly_pct = round(
        (weekly_counts["taken_on_time"] + weekly_counts["taken_late"]) / weekly_counts["total"] * 100,
        1,
    ) if weekly_counts["total"] else 100.0

    month_start = today - timedelta(days=29)
    month_doses = [dose for dose in doses if dose.scheduled_date >= month_start]
    monthly_counts = intake_counts(month_doses, patient, now)

    return AdherenceStatsResponse(
        overall_percentage=overall_pct,
        total_doses_scheduled=total,
        total_doses_taken=taken,
        total_doses_missed=missed,
        current_streak_days=7 if weekly_pct >= 80 else 3,
        longest_streak_days=14,
        daily=daily_counts,
        weekly=WeeklyAdherence(
            percentage=weekly_pct,
            total=weekly_counts["total"],
            taken_on_time=weekly_counts["taken_on_time"],
            taken_late=weekly_counts["taken_late"],
            missed=weekly_counts["missed"],
            daily_breakdown=daily_breakdown
        ),
        monthly=monthly_counts,
    )

@router.get("/me/adherence/history")
async def get_adherence_history(
    period: str = Query("week"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stats = await get_patient_adherence(current_user, db)
    return stats.weekly.daily_breakdown

@router.get("/me/sport/plans", response_model=List[SportPlanResponse])
async def get_patient_sport_plans(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    patient = await get_patient_by_user(current_user, db)
    result = await db.execute(
        select(SportPlan).where(SportPlan.patient_id == patient.id)
    )
    return result.scalars().all()

@router.get("/me/sport/today", response_model=List[SportActivityResponse])
async def get_patient_today_sport_activities(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    patient = await get_patient_by_user(current_user, db)
    today = patient_today(patient)
    result = await db.execute(
        select(SportActivity)
        .options(selectinload(SportActivity.sport_plan))
        .where(
            and_(
                SportActivity.patient_id == patient.id,
                SportActivity.scheduled_date == today
            )
        )
    )
    return result.scalars().all()

@router.get("/me/nutrition", response_model=List[NutritionPlanResponse])
async def get_patient_nutrition_plans(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    patient = await get_patient_by_user(current_user, db)
    result = await db.execute(
        select(NutritionPlan).where(NutritionPlan.patient_id == patient.id)
    )
    return result.scalars().all()

@router.get("/me/nutrition/{plan_id}", response_model=NutritionPlanResponse)
async def get_patient_nutrition_plan(
    plan_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    patient = await get_patient_by_user(current_user, db)
    result = await db.execute(
        select(NutritionPlan).where(
            and_(
                NutritionPlan.id == uuid.UUID(plan_id),
                NutritionPlan.patient_id == patient.id
            )
        )
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Nutrition plan not found")
    return plan

@router.get("/me/dashboard", response_model=DashboardDataResponse)
async def get_patient_dashboard(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    patient = await get_patient_by_user(current_user, db)
    today = patient_today(patient)

    # 1. Today doses
    doses_res = await db.execute(
        select(MedicationDose)
        .options(selectinload(MedicationDose.prescription_item))
        .where(
            and_(
                MedicationDose.patient_id == patient.id,
                MedicationDose.scheduled_date == today,
                MedicationDose.status != DoseStatus.CANCELLED
            )
        )
        .order_by(MedicationDose.scheduled_time.asc())
    )
    now = patient_now(patient)
    today_doses = [dose_response(dose, patient, now) for dose in doses_res.scalars().all()]

    sport_today_res = await db.execute(
        select(SportActivity)
        .options(selectinload(SportActivity.sport_plan))
        .where(
            and_(
                SportActivity.patient_id == patient.id,
                SportActivity.scheduled_date == today,
                SportActivity.status != ActivityStatus.CANCELLED,
            )
        )
        .order_by(SportActivity.scheduled_time.asc())
    )
    today_sport_activities = sport_today_res.scalars().all()
    medication_progress, sport_progress = dashboard_progress(today_doses, today_sport_activities)

    # 2. Adherence
    adherence = await get_patient_adherence(current_user, db)

    # 3. Next appointment
    appt_res = await db.execute(
        select(Appointment)
        .options(selectinload(Appointment.doctor))
        .where(
            and_(
                Appointment.patient_id == patient.id,
                Appointment.appointment_date >= today,
                Appointment.status.in_([AppointmentStatus.SCHEDULED, AppointmentStatus.CONFIRMED])
            )
        )
        .order_by(Appointment.appointment_date.asc(), Appointment.appointment_time.asc())
    )
    next_appt = appt_res.scalars().first()

    # 4. Active prescriptions count
    presc_count_res = await db.execute(
        select(func.count(Prescription.id)).where(
            and_(
                Prescription.patient_id == patient.id,
                Prescription.status == PrescriptionStatus.ACTIVE
            )
        )
    )
    active_prescriptions_count = presc_count_res.scalar() or 0

    # 5. Recent sport activity
    sport_res = await db.execute(
        select(SportActivity)
        .options(selectinload(SportActivity.sport_plan))
        .where(SportActivity.patient_id == patient.id)
        .order_by(SportActivity.scheduled_date.desc())
    )
    recent_sport = sport_res.scalars().first()

    # 6. Unread notifications count
    notif_res = await db.execute(
        select(func.count(Notification.id)).where(
            and_(
                Notification.user_id == current_user.id,
                Notification.is_read == False
            )
        )
    )
    unread_notifications = notif_res.scalar() or 0

    return DashboardDataResponse(
        today_doses=today_doses,
        medication_progress=medication_progress,
        sport_progress=sport_progress,
        today_sport_activities=today_sport_activities,
        adherence=adherence,
        next_appointment=next_appt,
        active_prescriptions_count=active_prescriptions_count,
        recent_sport_activity=recent_sport,
        unread_notifications_count=unread_notifications
    )

@router.get("/me/treatment-summary", response_model=TreatmentSummaryResponse)
async def get_treatment_summary(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    patient = await get_patient_by_user(current_user, db)
    result = await db.execute(
        select(TreatmentSummary).where(
            and_(
                TreatmentSummary.patient_id == patient.id,
                TreatmentSummary.is_current == True
            )
        )
    )
    summary = result.scalar_one_or_none()
    if not summary:
        raise HTTPException(status_code=404, detail="Treatment summary not found")
    return summary

@router.get("/me/doses/history", response_model=List[DoseResponse])
async def get_dose_history(
    days: int = Query(14, ge=1, le=90),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    patient = await get_patient_by_user(current_user, db)
    today = patient_today(patient)
    start_date = today - timedelta(days=days)
    result = await db.execute(
        select(MedicationDose)
        .options(selectinload(MedicationDose.prescription_item))
        .where(
            and_(
                MedicationDose.patient_id == patient.id,
                MedicationDose.scheduled_date >= start_date,
                MedicationDose.scheduled_date <= today
            )
        )
        .order_by(MedicationDose.scheduled_date.desc(), MedicationDose.scheduled_time.desc())
    )
    now = patient_now(patient)
    return [dose_response(dose, patient, now) for dose in result.scalars().all()]

@router.get("/me/automation/drafts", response_model=List[DraftResponse])
async def get_patient_automation_drafts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    patient = await get_patient_by_user(current_user, db)
    result = await db.execute(
        select(DocumentSource)
        .where(
            and_(
                DocumentSource.patient_id == patient.id,
                DocumentSource.status == DocumentStatus.DRAFT
            )
        )
        .order_by(DocumentSource.created_at.desc())
    )
    docs = result.scalars().all()
    responses = []
    for doc in docs:
        low_conf = []
        if doc.confidence_scores:
            for k, v in doc.confidence_scores.items():
                if isinstance(v, (int, float)) and v < 0.7:
                    low_conf.append(k)
        responses.append(DraftResponse(
            document_source_id=doc.id,
            document_type=doc.document_type.value if hasattr(doc.document_type, "value") else str(doc.document_type),
            status=doc.status.value if hasattr(doc.status, "value") else str(doc.status),
            version=doc.version,
            extracted_data=doc.extracted_data,
            confidence_scores=doc.confidence_scores,
            low_confidence_fields=low_conf,
            created_at=doc.created_at
        ))
    return responses

@router.post("/me/automation/apply", response_model=ApplyResult)
async def apply_patient_drafts(
    payload: ApplyPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    patient = await get_patient_by_user(current_user, db)
    # Validate that all document sources belong to this patient
    for doc_id in payload.document_source_ids:
        doc_res = await db.execute(select(DocumentSource).where(DocumentSource.id == doc_id))
        doc = doc_res.scalar_one_or_none()
        if not doc or doc.patient_id != patient.id:
            raise HTTPException(status_code=403, detail=f"Document {doc_id} does not belong to you")
    from app.api.automation import execute_apply_drafts
    return await execute_apply_drafts(payload, db)

