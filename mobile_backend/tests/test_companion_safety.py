import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.companion import send_message
from app.models.user import UserRole
from app.schemas.companion import MessageCreate
from app.schemas.companion import ConversationResponse
from app.services import companion


def test_multilingual_keyword_fallback():
    assert companion.keyword_triage("I want to kill myself") == "self_harm_or_suicide_risk"
    assert companion.keyword_triage("Je veux mourir") == "self_harm_or_suicide_risk"
    assert companion.keyword_triage("نحب نموت") == "self_harm_or_suicide_risk"
    assert companion.keyword_triage("I have chest pain") == "medical_emergency"
    assert companion.keyword_triage("ما نجمش نتنفس") == "medical_emergency"
    assert companion.keyword_triage("Can I stop taking this medicine?") == "medication_change_request"
    assert companion.keyword_triage("I feel sad") is None
    assert companion.keyword_triage("How much does a used car cost?") == "off_topic"
    assert companion.keyword_triage("Write me code to sort a list") == "off_topic"


def test_triage_uses_fast_model_and_routes_label(monkeypatch):
    import asyncio
    async def fake_anthropic(model, system, messages, max_tokens):
        assert model == companion.settings.TRIAGE_MODEL
        return '{"label":"medical_emergency"}'
    monkeypatch.setattr(companion, "_anthropic", fake_anthropic)
    label, source = asyncio.run(companion.triage("I have symptoms"))
    assert (label, source) == ("medical_emergency", "llm")


def test_triage_provider_failure_uses_keyword_fallback(monkeypatch):
    import asyncio
    async def unavailable(*args, **kwargs):
        raise RuntimeError("offline")
    monkeypatch.setattr(companion, "_anthropic", unavailable)
    assert asyncio.run(companion.triage("I want to kill myself")) == ("self_harm_or_suicide_risk", "keyword_fallback")
    assert asyncio.run(companion.triage("I feel a little low")) == ("distress", "keyword_fallback")


def test_companion_provider_failure_returns_localized_retryable_fallback(monkeypatch):
    import asyncio
    monkeypatch.setattr(companion.settings, "CHAT_N8N_CHAT_WEBHOOK_URL", "")
    monkeypatch.setattr(companion.settings, "CHAT_N8N_SHARED_SECRET", "")

    async def unavailable(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(companion, "_anthropic", unavailable)
    english = asyncio.run(companion.ask_companion_with_status("", "", [], "hello", "en"))
    french = asyncio.run(companion.ask_companion_with_status("", "", [], "bonjour", "fr"))
    assert english[1:] == (True, "CHAT_UPSTREAM_UNAVAILABLE")
    assert "réessayez" in french[0].lower()
    assert french[1:] == (True, "CHAT_UPSTREAM_UNAVAILABLE")


def test_n8n_response_parser_accepts_array_and_body_wrappers():
    response = companion._n8n_chat_response([{"json": {"body": {
        "reply": "Bonjour, je suis là.", "triage_label": "none", "language": "fr"
    }}}])
    assert response.reply.startswith("Bonjour")
    assert response.fallback is False


def test_rate_limit_blocks_excess_and_resets_after_window(monkeypatch):
    monkeypatch.setattr(companion.settings, "CHAT_RATE_LIMIT_PER_MINUTE", 2)
    key = "test-" + str(uuid4())
    assert companion.rate_limit_allows(key, now=10)
    assert companion.rate_limit_allows(key, now=11)
    assert not companion.rate_limit_allows(key, now=12)
    assert companion.rate_limit_allows(key, now=71)


def test_patient_cannot_send_to_another_patients_conversation():
    import asyncio
    user_id, patient_id, other_conversation = uuid4(), uuid4(), uuid4()
    current_user = SimpleNamespace(id=user_id, role=UserRole.PATIENT, language="en")
    patient = SimpleNamespace(id=patient_id, first_name="", last_name="", address=None, emergency_contact_phone=None)

    class Result:
        def __init__(self, value): self.value = value
        def scalar_one_or_none(self): return self.value

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[Result(patient), Result(SimpleNamespace(chat_consent=True)), Result(None)])
    with pytest.raises(HTTPException) as exc:
        asyncio.run(send_message(MessageCreate(conversation_id=other_conversation, content="hello"), current_user, db))
    assert exc.value.status_code == 404


def test_chat_requires_consent_before_accepting_message():
    import asyncio
    user_id, patient_id = uuid4(), uuid4()
    current_user = SimpleNamespace(id=user_id, role=UserRole.PATIENT, language="en")

    class Result:
        def __init__(self, value): self.value = value
        def scalar_one_or_none(self): return self.value

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[Result(SimpleNamespace(id=patient_id)), Result(None)])
    with pytest.raises(HTTPException) as exc:
        asyncio.run(send_message(MessageCreate(content="hello"), current_user, db))
    assert exc.value.status_code == 428
    assert db.execute.await_count == 2


def test_triage_risk_bypasses_normal_companion_reply(monkeypatch):
    import asyncio
    patient_id = uuid4()
    current_user = SimpleNamespace(id=uuid4(), role=UserRole.PATIENT, language="en")
    patient = SimpleNamespace(id=patient_id, first_name="", last_name="", address=None, emergency_contact_phone=None)
    consent = SimpleNamespace(chat_consent=True, share_with_doctor=False)

    class Result:
        def __init__(self, value=None, ids=None): self.value, self.ids = value, (ids or [])
        def scalar_one_or_none(self): return self.value
        def scalars(self): return self
        def all(self): return self.ids

    db = Mock()
    db.execute = AsyncMock(side_effect=[Result(patient), Result(consent), Result(ids=[])])
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = Mock()

    async def fake_anthropic(model, system, messages, max_tokens):
        return '{"label":"medical_emergency"}'

    monkeypatch.setattr(companion, "_anthropic", fake_anthropic)
    monkeypatch.setattr(companion, "ask_companion", AsyncMock(side_effect=AssertionError("normal reply must be bypassed")))
    response = asyncio.run(send_message(MessageCreate(content="I have unusual symptoms"), current_user, db))
    assert response.role == "assistant"
    assert response.triage_label == "medical_emergency"
    assert "urgent" in response.content.lower()
    assert any(type(call.args[0]).__name__ == "SafetyEvent" for call in db.add.call_args_list)


def test_rate_limit_returns_429_for_authenticated_patient(monkeypatch):
    import asyncio
    user_id, patient_id = uuid4(), uuid4()
    current_user = SimpleNamespace(id=user_id, role=UserRole.PATIENT, language="en")

    class Result:
        def __init__(self, value): self.value = value
        def scalar_one_or_none(self): return self.value

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[Result(SimpleNamespace(id=patient_id)), Result(SimpleNamespace(chat_consent=True))])
    db.add = Mock()
    import app.api.companion as companion_api
    monkeypatch.setattr(companion_api, "rate_limit_allows", lambda _: False)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(send_message(MessageCreate(content="hello"), current_user, db))
    assert exc.value.status_code == 429


def test_outgoing_context_redacts_identifiers(monkeypatch):
    import asyncio
    patient_id = uuid4()
    patient = SimpleNamespace(first_name="Alex", last_name="Example", address="12 River Road", emergency_contact_phone="+33123456789")
    summary = SimpleNamespace(
        diagnosis="Hypertension for Alex Example",
        patient_summary="Contact Alex at alex@example.test or +33123456789; address 12 River Road",
        treatment_goals=None, warnings=None,
    )

    class Result:
        def __init__(self, one=None, many=None): self.one, self.many = one, (many or [])
        def scalar_one_or_none(self): return self.one
        def scalars(self): return self
        def all(self): return self.many

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[Result(patient), Result(summary), Result(many=[]), Result(many=[])])
    context = asyncio.run(companion.build_context(db, patient_id))
    sent = {}

    async def fake_anthropic(model, system, messages, max_tokens):
        sent["payload"] = system + json.dumps(messages, ensure_ascii=False)
        return "I can explain the prescription in simple terms."

    monkeypatch.setattr(companion, "_anthropic", fake_anthropic)
    asyncio.run(companion.ask_companion(
        context, "Alex Example lives at 12 River Road", [],
        "Please explain my prescription. My name is Alex Example and I live at 12 River Road; call +33123456789",
        "en", patient,
    ))
    assert "Alex" not in sent["payload"]
    assert "Example" not in sent["payload"]
    assert "River Road" not in sent["payload"]
    assert "alex@example.test" not in sent["payload"]
    assert "+33123456789" not in sent["payload"]


def test_eval_fixture_contains_thirty_multilingual_cases():
    path = Path(__file__).parent / "evals" / "companion_triage.json"
    cases = json.loads(path.read_text(encoding="utf-8"))
    assert len(cases) == 30
    assert {case["expected"] for case in cases} == {
        "none", "distress", "self_harm_or_suicide_risk", "medical_emergency", "medication_change_request", "off_topic"
    }


def test_companion_responses_serialize_legacy_naive_timestamps_as_utc():
    from datetime import datetime, timezone
    conversation = ConversationResponse(
        id=uuid4(),
        created_at=datetime(2026, 10, 10, 23, 30),
        updated_at=datetime(2026, 10, 11, 0, 30, tzinfo=timezone.utc),
    )
    payload = conversation.model_dump(mode="json")
    assert payload["created_at"] == "2026-10-10T23:30:00Z"
    assert payload["updated_at"] == "2026-10-11T00:30:00Z"


def test_internal_context_token_is_bound_to_patient_and_session(monkeypatch):
    monkeypatch.setattr(companion.settings, "CHAT_N8N_SHARED_SECRET", "test-shared-secret")
    patient_id, session_id, other_patient = str(uuid4()), str(uuid4()), str(uuid4())
    token = companion.context_access_token(patient_id, session_id)
    assert token == companion.context_access_token(patient_id, session_id)
    assert token != companion.context_access_token(other_patient, session_id)
    assert token != companion.context_access_token(patient_id, str(uuid4()))


def test_n8n_chat_payload_is_minimized_and_carries_scoped_context_token(monkeypatch):
    import asyncio
    monkeypatch.setattr(companion.settings, "CHAT_N8N_CHAT_WEBHOOK_URL", "http://n8n.test/webhook/chat")
    monkeypatch.setattr(companion.settings, "CHAT_N8N_SHARED_SECRET", "test-shared-secret")
    patient_id, conversation_id = str(uuid4()), str(uuid4())
    patient = SimpleNamespace(first_name="Alex", last_name="Example", address="12 River Road", emergency_contact_phone="+33123456789")
    captured = {}

    class Response:
        def raise_for_status(self): pass
        def json(self): return {"reply": "I can help explain your care plan."}

    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
        async def post(self, url, headers, json):
            captured.update(url=url, headers=headers, payload=json)
            return Response()

    monkeypatch.setattr(companion.httpx, "AsyncClient", Client)
    reply = asyncio.run(companion.ask_companion(
        "private chart context should not be posted", "", [],
        "Please explain my dose. My name is Alex Example and address is 12 River Road; phone +33123456789",
        "en", patient, patient_id, conversation_id,
    ))
    assert reply == "I can help explain your care plan."
    payload = captured["payload"]
    assert payload["patient_id"] == patient_id
    assert payload["session_id"] == conversation_id
    assert payload["context_token"] == companion.context_access_token(patient_id, conversation_id)
    assert "private chart context" not in str(payload)
    assert "Alex" not in str(payload)
    assert "River Road" not in str(payload)
    assert "+33123456789" not in str(payload)
    assert captured["headers"]["X-HackCure-Secret"] == "test-shared-secret"
