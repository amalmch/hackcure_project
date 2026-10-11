import asyncio
import hmac
import httpx
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config import settings
from app.dependencies import get_current_user
from app.models.companion import CompanionConsent, CompanionConversation, CompanionMessage, MoodEntry, SafetyEvent, utc_now
from app.models.patient import Patient
from app.models.notification import Notification, NotificationCategory, NotificationPriority
from app.models.user import User, UserRole
from app.schemas.companion import (
    ConsentResponse, ConsentUpdate, ConversationResponse, MessageCreate, MessageResponse,
    MoodCreate, MoodResponse,
)
from app.services.companion import (
    ask_companion_with_status, build_context, emergency_numbers, notify_escalation, rate_limit_allows,
    safety_reply, triage, context_access_token,
)

router = APIRouter(prefix="/api/v1/chat", tags=["patient companion"])
logger = logging.getLogger(__name__)


def _localized_detail(language: str | None, key: str) -> str:
    messages = {
        "consent": ("Companion consent is required", "Votre consentement est nécessaire pour utiliser le compagnon.", "يلزم موافقتك لاستخدام الرفيق."),
        "rate_limit": ("Too many messages. Please wait a moment and try again.", "Vous envoyez trop de messages. Patientez un instant puis réessayez.", "أرسلت رسائل كثيرة. انتظر قليلاً ثم حاول مجدداً."),
    }
    index = 1 if (language or "en").startswith("fr") else 2 if (language or "en").startswith("ar") else 0
    return messages[key][index]


@router.get("/health")
async def chat_health(x_chat_diagnostics_token: str = Header(default="")):
    """Service diagnostics; intentionally protected by a separate service token."""
    expected = settings.CHAT_DIAGNOSTIC_TOKEN
    if not expected or not hmac.compare_digest(x_chat_diagnostics_token, expected):
        raise HTTPException(status_code=403, detail="Invalid diagnostics token")

    n8n = {"reachable": False, "workflow_active": False, "secret_accepted": False}
    if settings.CHAT_N8N_WEBHOOK_BASE_URL and settings.CHAT_N8N_SHARED_SECRET:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(
                    settings.CHAT_N8N_WEBHOOK_BASE_URL.rstrip("/") + "/webhook/hackcure-companion-health",
                    headers={"X-HackCure-Secret": settings.CHAT_N8N_SHARED_SECRET},
                )
            n8n["reachable"] = True
            n8n["workflow_active"] = response.status_code == 200
            n8n["secret_accepted"] = response.status_code == 200 and response.json().get("ok") is True
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            logger.warning("chat health probe failed step=n8n-health category=%s", type(exc).__name__)
    anthropic = {"configured": bool(settings.ANTHROPIC_API_KEY), "reachable": False}
    if settings.ANTHROPIC_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(
                    "https://api.anthropic.com/v1/models",
                    headers={"x-api-key": settings.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01"},
                )
            anthropic["reachable"] = response.is_success
            anthropic["status_code"] = response.status_code
        except httpx.HTTPError as exc:
            logger.warning("chat health probe failed step=anthropic-health category=%s", type(exc).__name__)
    return {
        "backend": {"reachable": True},
        "n8n": n8n,
        "anthropic": anthropic,
        "chat_ready": anthropic["reachable"] or n8n["secret_accepted"],
    }


async def _patient(current_user: User, db: AsyncSession) -> Patient:
    if current_user.role != UserRole.PATIENT:
        raise HTTPException(status_code=403, detail="Patient account required")
    result = await db.execute(select(Patient).where(Patient.user_id == current_user.id))
    patient = result.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")
    return patient


@router.get("/consent", response_model=ConsentResponse)
async def get_consent(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    patient = await _patient(current_user, db)
    result = await db.execute(select(CompanionConsent).where(CompanionConsent.patient_id == patient.id))
    consent = result.scalar_one_or_none()
    return consent or ConsentResponse(chat_consent=False, share_with_doctor=False)


@router.put("/consent", response_model=ConsentResponse)
async def update_consent(payload: ConsentUpdate, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    patient = await _patient(current_user, db)
    result = await db.execute(select(CompanionConsent).where(CompanionConsent.patient_id == patient.id))
    consent = result.scalar_one_or_none()
    if consent is None:
        consent = CompanionConsent(patient_id=patient.id)
        db.add(consent)
    consent.chat_consent = payload.chat_consent
    consent.share_with_doctor = payload.share_with_doctor if payload.chat_consent else False
    consent.updated_at = utc_now()
    await db.commit()
    await db.refresh(consent)
    return consent


@router.get("/emergency-contacts")
async def get_emergency_contacts(current_user: User = Depends(get_current_user)):
    # Contacts are loaded from reviewed, local configuration; unknown countries return no guessed numbers.
    return {"country": settings.CHAT_DEFAULT_COUNTRY, "numbers": emergency_numbers()}


@router.post("/conversations", response_model=ConversationResponse)
async def create_conversation(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    patient = await _patient(current_user, db)
    consent_result = await db.execute(select(CompanionConsent).where(CompanionConsent.patient_id == patient.id))
    consent = consent_result.scalar_one_or_none()
    if not consent or not consent.chat_consent:
        raise HTTPException(status_code=428, detail=_localized_detail(current_user.language, "consent"))
    conversation = CompanionConversation(patient_id=patient.id)
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


@router.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    patient = await _patient(current_user, db)
    result = await db.execute(
        select(CompanionConversation).where(CompanionConversation.patient_id == patient.id)
        .order_by(CompanionConversation.updated_at.desc()).limit(100)
    )
    return result.scalars().all()


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageResponse])
async def list_messages(conversation_id: UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    patient = await _patient(current_user, db)
    conv_result = await db.execute(select(CompanionConversation).where(
        CompanionConversation.id == conversation_id, CompanionConversation.patient_id == patient.id
    ))
    if not conv_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Conversation not found")
    result = await db.execute(
        select(CompanionMessage).where(CompanionMessage.conversation_id == conversation_id)
        .order_by(CompanionMessage.created_at.asc()).limit(500)
    )
    return result.scalars().all()


@router.post("/messages", response_model=MessageResponse)
async def send_message(payload: MessageCreate, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    patient = await _patient(current_user, db)
    consent_result = await db.execute(select(CompanionConsent).where(CompanionConsent.patient_id == patient.id))
    consent = consent_result.scalar_one_or_none()
    if not consent or not consent.chat_consent:
        raise HTTPException(status_code=428, detail=_localized_detail(current_user.language, "consent"))
    if not rate_limit_allows(str(current_user.id)):
        raise HTTPException(status_code=429, detail=_localized_detail(current_user.language, "rate_limit"))

    if payload.conversation_id:
        conv_result = await db.execute(select(CompanionConversation).where(
            CompanionConversation.id == payload.conversation_id, CompanionConversation.patient_id == patient.id
        ))
        conversation = conv_result.scalar_one_or_none()
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        conversation = CompanionConversation(patient_id=patient.id)
        db.add(conversation)
        await db.flush()

    cached_assistant = None
    patient_message = None
    if payload.client_message_id:
        duplicate_result = await db.execute(select(CompanionMessage).where(CompanionMessage.id == payload.client_message_id))
        patient_message = duplicate_result.scalar_one_or_none()
        if patient_message and patient_message.conversation_id != conversation.id:
            raise HTTPException(status_code=409, detail="Message retry belongs to another conversation")
        if patient_message:
            cached_result = await db.execute(
                select(CompanionMessage).where(
                    CompanionMessage.conversation_id == conversation.id,
                    CompanionMessage.role == "assistant",
                    CompanionMessage.created_at >= patient_message.created_at,
                ).order_by(CompanionMessage.created_at.asc()).limit(1)
            )
            cached_assistant = cached_result.scalar_one_or_none()
    if cached_assistant:
        return cached_assistant
    if patient_message is None:
        patient_message = CompanionMessage(
            id=payload.client_message_id or uuid4(),
            conversation_id=conversation.id,
            role="user",
            content=payload.content.strip(),
        )
        db.add(patient_message)
    triage_label, triage_source = await triage(payload.content, patient)
    is_fallback = False
    error_code = None
    if triage_label in {"self_harm_or_suicide_risk", "medical_emergency", "medication_change_request"}:
        reply = safety_reply(triage_label, current_user.language or "en")
        db.add(SafetyEvent(patient_id=patient.id, conversation_id=conversation.id, category=triage_label, source=triage_source))
        if consent.share_with_doctor:
            asyncio.create_task(notify_escalation(str(patient.id), triage_label))
    else:
        context = "" if settings.CHAT_N8N_CHAT_WEBHOOK_URL else await build_context(db, patient.id)
        history_result = await db.execute(
            select(CompanionMessage).where(CompanionMessage.conversation_id == conversation.id)
            .order_by(CompanionMessage.created_at.desc()).limit(12)
        )
        history = [item for item in reversed(history_result.scalars().all()) if item.id != patient_message.id][-12:]
        reply, is_fallback, error_code = await ask_companion_with_status(
            context, conversation.rolling_summary, history, payload.content,
            current_user.language or "en", patient, str(patient.id), str(conversation.id),
        )

    response_message = CompanionMessage(
        id=uuid4(), conversation_id=conversation.id, role="assistant", content=reply,
        triage_label=triage_label, created_at=utc_now(),
    )
    if not is_fallback:
        db.add(response_message)
    conversation.updated_at = utc_now()
    all_count_result = await db.execute(select(CompanionMessage.id).where(CompanionMessage.conversation_id == conversation.id))
    if not is_fallback and len(all_count_result.scalars().all()) >= 24:
        recent_result = await db.execute(
            select(CompanionMessage).where(CompanionMessage.conversation_id == conversation.id)
            .order_by(CompanionMessage.created_at.desc()).limit(12)
        )
        recent = list(reversed(recent_result.scalars().all()))
        conversation.rolling_summary = " ".join(f"{m.role}: {m.content[:220]}" for m in recent)[-1600:]
    await db.commit()
    if not is_fallback:
        await db.refresh(response_message)
    return MessageResponse(
        id=response_message.id,
        conversation_id=conversation.id,
        role="assistant",
        content=reply,
        triage_label=triage_label,
        language=current_user.language or "en",
        created_at=response_message.created_at,
        fallback=is_fallback,
        error_code=error_code,
    )


@router.post("/moods", response_model=MoodResponse)
async def add_mood(payload: MoodCreate, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    patient = await _patient(current_user, db)
    consent_result = await db.execute(select(CompanionConsent).where(CompanionConsent.patient_id == patient.id))
    consent = consent_result.scalar_one_or_none()
    if not consent or not consent.chat_consent:
        raise HTTPException(status_code=428, detail=_localized_detail(current_user.language, "consent"))
    entry = MoodEntry(patient_id=patient.id, mood=payload.mood, note=payload.note)
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


@router.get("/moods", response_model=list[MoodResponse])
async def list_moods(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    patient = await _patient(current_user, db)
    consent_result = await db.execute(select(CompanionConsent).where(CompanionConsent.patient_id == patient.id))
    consent = consent_result.scalar_one_or_none()
    if not consent or not consent.chat_consent:
        raise HTTPException(status_code=428, detail=_localized_detail(current_user.language, "consent"))
    result = await db.execute(
        select(MoodEntry).where(MoodEntry.patient_id == patient.id).order_by(MoodEntry.created_at.desc()).limit(90)
    )
    return result.scalars().all()


async def verify_n8n_secret(x_hackcure_secret: str = Header(default="")) -> None:
    if not settings.CHAT_N8N_SHARED_SECRET or not hmac.compare_digest(x_hackcure_secret, settings.CHAT_N8N_SHARED_SECRET):
        raise HTTPException(status_code=403, detail="Invalid workflow credential")


@router.post("/internal/daily-check-in", dependencies=[Depends(verify_n8n_secret)])
async def send_daily_checkins(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(CompanionConsent, Patient).join(Patient, CompanionConsent.patient_id == Patient.id)
        .where(CompanionConsent.chat_consent.is_(True))
    )
    rows = result.all()
    for consent, patient in rows:
        db.add(Notification(
            user_id=patient.user_id,
            title="Daily wellbeing check-in",
            body="Take a moment to notice how you feel today. You can check in with your wellbeing companion.",
            category=NotificationCategory.SYSTEM,
            priority=NotificationPriority.LOW,
            data={"type": "wellbeing_checkin"},
        ))
    await db.commit()
    return {"scheduled": len(rows)}


@router.post("/internal/weekly-mood-summary", dependencies=[Depends(verify_n8n_secret)])
async def get_weekly_mood_summaries(db: AsyncSession = Depends(get_db)):
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)
    result = await db.execute(
        select(MoodEntry.patient_id, func.count(MoodEntry.id), func.avg(MoodEntry.mood))
        .join(CompanionConsent, CompanionConsent.patient_id == MoodEntry.patient_id)
        .where(CompanionConsent.chat_consent.is_(True), CompanionConsent.share_with_doctor.is_(True), MoodEntry.created_at >= since)
        .group_by(MoodEntry.patient_id)
    )
    return {"summaries": [
        {"patient_ref": str(patient_id), "checkins": int(count), "average_mood": round(float(average), 1)}
        for patient_id, count, average in result.all() if count
    ]}


@router.get("/internal/patients/{patient_id}/context", dependencies=[Depends(verify_n8n_secret)])
async def get_minimized_patient_context(
    patient_id: UUID,
    session_id: UUID,
    x_hackcure_context_token: str = Header(default=""),
    db: AsyncSession = Depends(get_db),
):
    expected = context_access_token(str(patient_id), str(session_id))
    if not hmac.compare_digest(x_hackcure_context_token, expected):
        raise HTTPException(status_code=403, detail="Invalid patient context authorization")
    patient_result = await db.execute(select(Patient).where(Patient.id == patient_id))
    if patient_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Patient context not found")
    return {"context": await build_context(db, patient_id)}
