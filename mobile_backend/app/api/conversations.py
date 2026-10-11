import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from sqlalchemy.orm import selectinload
from typing import List
from datetime import datetime
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.patient import Patient
from app.models.doctor import Doctor
from app.models.conversation import Conversation, Message, SenderRole, ConversationStatus
from app.schemas.conversation import (
    ConversationResponse, MessageResponse,
    CreateConversationPayload, SendMessagePayload
)
from app.schemas.doctor import DoctorResponse
from app.websocket.manager import manager

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])

@router.get("", response_model=List[ConversationResponse])
async def get_conversations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    patient_res = await db.execute(select(Patient).where(Patient.user_id == current_user.id))
    patient = patient_res.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")

    result = await db.execute(
        select(Conversation)
        .where(Conversation.patient_id == patient.id)
        .order_by(Conversation.last_message_at.desc())
    )
    conversations = result.scalars().all()

    response_list = []
    for conv in conversations:
        # Load doctor
        doc_res = await db.execute(select(Doctor).where(Doctor.id == conv.doctor_id))
        doctor = doc_res.scalar_one_or_none()

        # Load last message
        last_msg_res = await db.execute(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.created_at.desc())
        )
        last_message = last_msg_res.scalars().first()

        # Count unread messages from doctor
        unread_res = await db.execute(
            select(func.count(Message.id)).where(
                and_(
                    Message.conversation_id == conv.id,
                    Message.sender_role == SenderRole.DOCTOR,
                    Message.is_read == False
                )
            )
        )
        unread_count = unread_res.scalar() or 0

        conv_dict = {
            "id": conv.id,
            "patient_id": conv.patient_id,
            "doctor_id": conv.doctor_id,
            "subject": conv.subject,
            "category": conv.category.value if conv.category else None,
            "status": conv.status.value if conv.status else "ACTIVE",
            "last_message_at": conv.last_message_at,
            "created_at": conv.created_at,
            "updated_at": conv.updated_at,
            "doctor": DoctorResponse.model_validate(doctor) if doctor else None,
            "last_message": MessageResponse.model_validate(last_message) if last_message else None,
            "unread_count": unread_count,
        }
        response_list.append(ConversationResponse(**conv_dict))

    return response_list

@router.post("", response_model=ConversationResponse)
async def create_conversation(
    payload: CreateConversationPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    patient_res = await db.execute(select(Patient).where(Patient.user_id == current_user.id))
    patient = patient_res.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")

    new_conv = Conversation(
        patient_id=patient.id,
        doctor_id=payload.doctor_id,
        subject=payload.subject or "Consultation",
        category=payload.category,
        status=ConversationStatus.ACTIVE,
        last_message_at=datetime.utcnow()
    )
    db.add(new_conv)
    await db.flush()

    initial_msg = Message(
        conversation_id=new_conv.id,
        sender_id=current_user.id,
        sender_role=SenderRole.PATIENT,
        content=payload.initial_message,
        is_read=True
    )
    db.add(initial_msg)
    await db.commit()
    await db.refresh(new_conv)
    await db.refresh(initial_msg)

    doc_res = await db.execute(select(Doctor).where(Doctor.id == payload.doctor_id))
    doctor = doc_res.scalar_one_or_none()

    return ConversationResponse(
        id=new_conv.id,
        patient_id=new_conv.patient_id,
        doctor_id=new_conv.doctor_id,
        subject=new_conv.subject,
        category=new_conv.category.value if new_conv.category else None,
        status=new_conv.status.value,
        last_message_at=new_conv.last_message_at,
        created_at=new_conv.created_at,
        doctor=DoctorResponse.model_validate(doctor) if doctor else None,
        last_message=MessageResponse.model_validate(initial_msg),
        unread_count=0
    )

@router.get("/{conversation_id}/messages", response_model=List[MessageResponse])
async def get_messages(
    conversation_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    patient_res = await db.execute(select(Patient).where(Patient.user_id == current_user.id))
    patient = patient_res.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")

    conv_res = await db.execute(
        select(Conversation).where(
            and_(
                Conversation.id == uuid.UUID(conversation_id),
                Conversation.patient_id == patient.id
            )
        )
    )
    conv = conv_res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Fetch messages
    offset = (page - 1) * limit
    msg_res = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at.asc())
        .offset(offset)
        .limit(limit)
    )
    messages = msg_res.scalars().all()

    # Mark doctor's messages as read
    updated = False
    for m in messages:
        if m.sender_role == SenderRole.DOCTOR and not m.is_read:
            m.is_read = True
            m.read_at = datetime.utcnow()
            updated = True
    if updated:
        await db.commit()

    return messages

@router.post("/{conversation_id}/messages", response_model=MessageResponse)
async def send_message(
    conversation_id: str,
    payload: SendMessagePayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    patient_res = await db.execute(select(Patient).where(Patient.user_id == current_user.id))
    patient = patient_res.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")

    conv_res = await db.execute(
        select(Conversation).where(
            and_(
                Conversation.id == uuid.UUID(conversation_id),
                Conversation.patient_id == patient.id
            )
        )
    )
    conv = conv_res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    now = datetime.utcnow()
    new_msg = Message(
        conversation_id=conv.id,
        sender_id=current_user.id,
        sender_role=SenderRole.PATIENT,
        content=payload.content,
        created_at=now
    )
    db.add(new_msg)
    conv.last_message_at = now

    await db.commit()
    await db.refresh(new_msg)

    # Broadcast via websocket to connected doctor
    doc_res = await db.execute(select(Doctor).where(Doctor.id == conv.doctor_id))
    doc = doc_res.scalar_one_or_none()
    if doc:
        await manager.send_personal_message(
            {
                "type": "NEW_MESSAGE",
                "conversation_id": str(conv.id),
                "message": MessageResponse.model_validate(new_msg).model_dump(mode="json")
            },
            str(doc.user_id)
        )

    return new_msg
