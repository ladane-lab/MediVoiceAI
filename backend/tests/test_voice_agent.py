"""Phase 4 automated tests for voice tools, confirmation state, and mocked Pipecat pipeline."""

from datetime import date, timedelta
from unittest.mock import MagicMock, patch
import asyncio
from fastapi.testclient import TestClient
from pipecat.frames.frames import (
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TranscriptionFrame,
)
from pipecat.processors.frame_processor import FrameDirection
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.database import Base
from app.main import app
from app.routes.voice import get_voice_session_manager
from app.seed import seed_doctors
from app.voice.agent import (
    AssistantEventsObserver,
    UserTurnTranscriptObserver,
    VoiceConfigurationError,
    build_voice_pipeline,
    validate_voice_configuration,
)
from app.voice.prompts import build_system_prompt
from app.voice.session import VoiceSessionManager, VoiceSessionRecord
from app.voice.tools import (
    VoiceConversationState,
    build_voice_tools,
    tool_book_appointment,
    tool_cancel_appointment,
    tool_check_doctor_availability,
    tool_confirm_cancellation,
    tool_confirm_phone_number,
    tool_list_appointments,
    tool_list_doctors,
)


def next_weekday(weekday_index: int) -> date:
    """Return the next future date matching weekday_index (0=Mon .. 6=Sun)."""
    today = date.today()
    days_ahead = (weekday_index - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return today + timedelta(days=days_ahead)


@pytest.fixture()
def isolated_db(tmp_path):
    """Create an isolated SQLite test database seeded with the 6 doctors."""
    db_file = tmp_path / "test_voice.db"
    engine = create_engine(
        f"sqlite:///{db_file.as_posix()}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    seed_doctors(db)
    yield db, TestingSessionLocal
    db.close()
    engine.dispose()


def test_tool_argument_validation_and_doctor_listing(isolated_db):
    """Verify doctor listing, speciality filtering, and invalid tool arguments."""
    db, _ = isolated_db

    all_docs = tool_list_doctors(db=db)
    assert all_docs["success"] is True
    assert all_docs["total"] == 6

    cardio = tool_list_doctors(speciality="Cardiologist", db=db)
    assert cardio["total"] == 1
    assert cardio["doctors"][0]["name"] == "Dr. Ananya Sharma"

    bad_doc_avail = tool_check_doctor_availability(
        doctor_id="not-an-int",
        appointment_date=next_weekday(0).isoformat(),
        db=db,
    )
    assert bad_doc_avail["success"] is False
    assert bad_doc_avail["error_code"] == "invalid_arguments"

    bad_date_avail = tool_check_doctor_availability(
        doctor_id=1,
        appointment_date="invalid-date",
        db=db,
    )
    assert bad_date_avail["success"] is False
    assert bad_date_avail["error_code"] == "invalid_appointment_date"


def test_availability_tool_invocation(isolated_db):
    """Verify check_doctor_availability returns real slots from Phase 3 service."""
    db, _ = isolated_db
    monday = next_weekday(0).isoformat()

    res = tool_check_doctor_availability(doctor_id=1, appointment_date=monday, db=db)
    assert res["success"] is True
    assert res["doctor_name"] == "Dr. Ananya Sharma"
    assert "09:00" in res["available_slots"]


def test_booking_rejected_without_confirmed_phone_and_succeeds_after(isolated_db):
    """Enforce digit-by-digit phone confirmation before booking."""
    db, _ = isolated_db
    state = VoiceConversationState()
    monday = next_weekday(0).isoformat()

    # Attempt 1: Calling book_appointment directly without phone confirmation fails.
    blocked = tool_book_appointment(
        state=state,
        doctor_id=1,
        patient_phone_number="+91 98765-43210",
        appointment_date=monday,
        appointment_time="10:00",
        db=db,
    )
    assert blocked["success"] is False
    assert blocked["requires_phone_confirmation"] is True
    assert "plus 9 1" in blocked["digit_by_digit"]

    # Attempt 2: Gemini cannot confirm on the very same turn before the caller responds.
    same_turn = tool_confirm_phone_number(
        state=state,
        phone_number="+919876543210",
        caller_confirmed=True,
    )
    assert same_turn["confirmed"] is False

    # Caller hears the readback and says "No, that's wrong" -> gate resets.
    state.record_user_turn("No, that is wrong")
    rejected = tool_confirm_phone_number(
        state=state,
        phone_number="+919876543210",
        caller_confirmed=True,
    )
    assert rejected["confirmed"] is False

    # Caller speaks the number again, assistant stages it, caller confirms in next turn.
    state.record_user_turn("9876543210")
    staged = tool_confirm_phone_number(
        state=state,
        phone_number="9876543210",
        caller_confirmed=False,
    )
    assert staged["confirmed"] is False
    assert staged["phone_number"] == "+919876543210"

    state.record_user_turn("Yes, that is correct")
    confirmed = tool_confirm_phone_number(
        state=state,
        phone_number="+919876543210",
        caller_confirmed=True,
    )
    assert confirmed["confirmed"] is True

    booked = tool_book_appointment(
        state=state,
        doctor_id=1,
        patient_phone_number="+919876543210",
        appointment_date=monday,
        appointment_time="10:00",
        patient_name="Rahul",
        db=db,
    )
    assert booked["success"] is True
    assert booked["appointment"]["status"] == "booked"
    assert booked["appointment"]["patient_phone_number"] == "+919876543210"


def test_lookup_and_two_step_cancellation_enforcement(isolated_db):
    """Enforce both phone confirmation and explicit cancellation approval."""
    db, _ = isolated_db
    state = VoiceConversationState()
    monday = next_weekday(0).isoformat()

    # Lookup must fail before phone confirmation.
    blocked_lookup = tool_list_appointments(
        state=state,
        patient_phone_number="+919876543210",
        db=db,
    )
    assert blocked_lookup["success"] is False
    assert blocked_lookup["requires_phone_confirmation"] is True

    # Confirm phone number across turns and book an appointment.
    state.record_user_turn("My number is +919876543210")
    tool_confirm_phone_number(state=state, phone_number="+919876543210", caller_confirmed=False)
    state.record_user_turn("Yes correct")
    tool_confirm_phone_number(state=state, phone_number="+919876543210", caller_confirmed=True)

    booked = tool_book_appointment(
        state=state,
        doctor_id=1,
        patient_phone_number="+919876543210",
        appointment_date=monday,
        appointment_time="10:20",
        db=db,
    )
    assert booked["success"] is True
    appt_id = booked["appointment"]["id"]

    # Lookup succeeds after confirmation.
    found = tool_list_appointments(state=state, patient_phone_number="+919876543210", db=db)
    assert found["success"] is True
    assert found["total"] == 1

    # Attempt cancellation without explicit cancellation approval -> blocked & staged.
    blocked_cancel = tool_cancel_appointment(
        state=state,
        appointment_id=appt_id,
        patient_phone_number="+919876543210",
        db=db,
    )
    assert blocked_cancel["success"] is False
    assert blocked_cancel["requires_cancellation_confirmation"] is True

    # Gemini cannot confirm cancellation on the same turn before caller responds.
    same_turn_cancel = tool_confirm_cancellation(
        state=state,
        appointment_id=appt_id,
        patient_phone_number="+919876543210",
        caller_confirmed=True,
        db=db,
    )
    assert same_turn_cancel["cancellation_confirmed"] is False

    # Caller explicitly approves cancellation on the next turn.
    state.record_user_turn("Yes, please cancel it")
    approved_cancel = tool_confirm_cancellation(
        state=state,
        appointment_id=appt_id,
        patient_phone_number="+919876543210",
        caller_confirmed=True,
        db=db,
    )
    assert approved_cancel["cancellation_confirmed"] is True

    cancelled = tool_cancel_appointment(
        state=state,
        appointment_id=appt_id,
        patient_phone_number="+919876543210",
        db=db,
    )
    assert cancelled["success"] is True
    assert cancelled["status"] == "cancelled"


def test_cross_patient_cancellation_blocked_in_voice_tools(isolated_db):
    """Caller cannot cancel another patient's appointment via voice tools."""
    db, _ = isolated_db
    monday = next_weekday(0).isoformat()

    owner_state = VoiceConversationState()
    owner_state.record_user_turn("+919876543210")
    tool_confirm_phone_number(owner_state, "+919876543210", False)
    owner_state.record_user_turn("yes")
    tool_confirm_phone_number(owner_state, "+919876543210", True)
    booked = tool_book_appointment(
        state=owner_state,
        doctor_id=1,
        patient_phone_number="+919876543210",
        appointment_date=monday,
        appointment_time="10:40",
        db=db,
    )
    appt_id = booked["appointment"]["id"]

    other_state = VoiceConversationState()
    other_state.record_user_turn("+919800000001")
    tool_confirm_phone_number(other_state, "+919800000001", False)
    other_state.record_user_turn("yes")
    tool_confirm_phone_number(other_state, "+919800000001", True)

    denied = tool_cancel_appointment(
        state=other_state,
        appointment_id=appt_id,
        patient_phone_number="+919800000001",
        db=db,
    )
    assert denied["success"] is False
    assert denied["error_code"] == "forbidden_cancellation"


def test_missing_api_keys_handled_cleanly():
    """Missing Gemini or ElevenLabs credentials return clear 503 config errors."""
    empty_settings = Settings(
        _env_file=None,
        gemini_api_key="",
        elevenlabs_api_key="your_elevenlabs_api_key_here",
        elevenlabs_voice_id="",
    )
    with pytest.raises(VoiceConfigurationError) as exc_info:
        validate_voice_configuration(empty_settings)
    assert set(exc_info.value.missing_vars) == {
        "GEMINI_API_KEY",
        "ELEVENLABS_API_KEY",
        "ELEVENLABS_VOICE_ID",
    }

    manager = VoiceSessionManager(settings=empty_settings)
    status_info = manager.get_status()
    assert status_info["ready"] is False
    assert len(status_info["missing_env_vars"]) == 3

    app.dependency_overrides[get_voice_session_manager] = lambda: manager
    try:
        with TestClient(app) as client:
            status_res = client.get("/api/voice/status")
            assert status_res.status_code == 200
            assert status_res.json()["ready"] is False

            create_res = client.post("/api/voice/sessions")
            assert create_res.status_code == 503
            assert "GEMINI_API_KEY" in create_res.json()["detail"]

            offer_res = client.post(
                "/api/voice/offer",
                json={"sdp": "v=0", "type": "offer"},
            )
            assert offer_res.status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_mocked_pipecat_pipeline_and_tools_schema(isolated_db):
    """Build Pipecat pipeline with mocked Gemini, ElevenLabs, and WebRTC transport."""
    _db, session_factory = isolated_db
    configured_settings = Settings(
        _env_file=None,
        gemini_api_key="test-gemini-key",
        gemini_model="gemini-3.6-flash",
        elevenlabs_api_key="test-elevenlabs-key",
        elevenlabs_voice_id="test-voice-id",
    )

    state = VoiceConversationState()
    tools = build_voice_tools(state, db_session_factory=session_factory)
    tool_names = [t.name for t in tools.standard_tools]
    assert tool_names == [
        "list_doctors",
        "check_doctor_availability",
        "confirm_phone_number",
        "book_appointment",
        "list_appointments",
        "confirm_cancellation",
        "cancel_appointment",
    ]

    prompt = build_system_prompt(date(2026, 11, 25))
    assert "2026-11-25" in prompt
    assert "confirm_phone_number" in prompt

    mock_connection = MagicMock()
    mock_connection.pc_id = "pc-test-1"

    with (
        patch("app.voice.agent.ElevenLabsRealtimeSTTService") as mock_stt,
        patch("app.voice.agent.ElevenLabsTTSService") as mock_tts,
        patch("app.voice.agent.GoogleLLMService") as mock_llm,
        patch("app.voice.agent.SileroVADAnalyzer") as mock_vad,
        patch("app.voice.agent.SmallWebRTCTransport") as mock_transport,
        patch("app.voice.agent.LLMContextAggregatorPair") as mock_agg,
        patch("app.voice.agent.Pipeline") as mock_pipeline,
        patch("app.voice.agent.PipelineTask") as mock_task,
    ):
        mock_agg.return_value.user.return_value = MagicMock()
        mock_agg.return_value.assistant.return_value = MagicMock()

        bundle = build_voice_pipeline(
            webrtc_connection=mock_connection,
            settings=configured_settings,
            state=state,
        )
        assert bundle.state is state
        mock_stt.assert_called_once()
        mock_tts.assert_called_once()
        mock_llm.assert_called_once()
        mock_vad.assert_called_once()
        mock_transport.assert_called_once()
        mock_pipeline.assert_called_once()
        mock_task.assert_called_once()


def test_phone_confirmation_rejects_unrelated_silence_and_number_change(isolated_db):
    """Section 8: Unrelated speech, silence, negative replies, and number changes must not confirm."""
    db, _ = isolated_db
    state = VoiceConversationState()
    monday = next_weekday(0).isoformat()

    # Stage phone number
    state.record_user_turn("My number is +919876543210")
    tool_confirm_phone_number(state, "+919876543210", caller_confirmed=False)

    # Silence (empty transcript) must NOT confirm even if Gemini passes caller_confirmed=True
    state.record_user_turn("   ")
    res_silence = tool_confirm_phone_number(state, "+919876543210", caller_confirmed=True)
    assert res_silence["confirmed"] is False

    # Unrelated speech must NOT confirm even if Gemini passes caller_confirmed=True
    state.record_user_turn("What time is Dr. Sharma free tomorrow?")
    res_unrelated = tool_confirm_phone_number(state, "+919876543210", caller_confirmed=True)
    assert res_unrelated["confirmed"] is False

    # Mixed negative/hesitation speech must NOT confirm
    state.record_user_turn("Yes, wait, the last digit is wrong")
    res_mixed = tool_confirm_phone_number(state, "+919876543210", caller_confirmed=True)
    assert res_mixed["confirmed"] is False

    # Re-stage and confirm explicitly with "That's right"
    state.record_user_turn("9876543210")
    tool_confirm_phone_number(state, "+919876543210", caller_confirmed=False)
    state.record_user_turn("Yes, that's right")
    res_ok = tool_confirm_phone_number(state, "+919876543210", caller_confirmed=True)
    assert res_ok["confirmed"] is True

    # Speaking a different phone number must invalidate the previous confirmation
    state.record_user_turn("Actually use 9123456789")
    assert state.is_phone_confirmed("+919876543210") is False
    blocked = tool_book_appointment(
        state=state,
        doctor_id=1,
        patient_phone_number="+919876543210",
        appointment_date=monday,
        appointment_time="10:00",
        db=db,
    )
    assert blocked["success"] is False
    assert blocked["requires_phone_confirmation"] is True


def test_cancellation_confirmation_rejects_unrelated_and_negative_speech(isolated_db):
    """Section 8: Cancellation must reject unrelated speech, silence, and negative replies."""
    db, _ = isolated_db
    state = VoiceConversationState()
    monday = next_weekday(0).isoformat()

    state.record_user_turn("+919876543210")
    tool_confirm_phone_number(state, "+919876543210", False)
    state.record_user_turn("Correct")
    tool_confirm_phone_number(state, "+919876543210", True)

    booked = tool_book_appointment(
        state=state,
        doctor_id=1,
        patient_phone_number="+919876543210",
        appointment_date=monday,
        appointment_time="11:00",
        db=db,
    )
    appt_id = booked["appointment"]["id"]

    # Stage cancellation (reads appointment details back)
    staged = tool_confirm_cancellation(state, appt_id, "+919876543210", caller_confirmed=False, db=db)
    assert staged["requires_cancellation_confirmation"] is True

    # Silence does not confirm
    state.record_user_turn("")
    res_silence = tool_confirm_cancellation(state, appt_id, "+919876543210", caller_confirmed=True, db=db)
    assert res_silence["cancellation_confirmed"] is False

    # Unrelated question does not confirm
    state.record_user_turn("By the way, what is the consultation fee?")
    res_unrelated = tool_confirm_cancellation(state, appt_id, "+919876543210", caller_confirmed=True, db=db)
    assert res_unrelated["cancellation_confirmed"] is False

    # Negative response resets pending cancellation
    state.record_user_turn("No, keep my appointment")
    res_reject = tool_confirm_cancellation(state, appt_id, "+919876543210", caller_confirmed=True, db=db)
    assert res_reject["cancellation_confirmed"] is False
    assert state.pending_cancellation_id is None

    # Re-stage and confirm explicitly
    tool_confirm_cancellation(state, appt_id, "+919876543210", caller_confirmed=False, db=db)
    state.record_user_turn("Yes, confirm cancellation")
    res_approved = tool_confirm_cancellation(state, appt_id, "+919876543210", caller_confirmed=True, db=db)
    assert res_approved["cancellation_confirmed"] is True


def test_transcript_observers_emit_and_deduplicate_events():
    """Verify UserTurnTranscriptObserver and AssistantEventsObserver record and emit transcripts."""
    mock_conn = MagicMock()
    record = VoiceSessionRecord(session_id="sess-1", connection=mock_conn)

    user_obs = UserTurnTranscriptObserver(record.state, on_event=record.record_and_emit_event)
    assistant_obs = AssistantEventsObserver(on_event=record.record_and_emit_event)
    user_obs.push_frame = MagicMock(side_effect=lambda f, d: asyncio.sleep(0))
    assistant_obs.push_frame = MagicMock(side_effect=lambda f, d: asyncio.sleep(0))

    async def _run():
        await user_obs.process_frame(
            TranscriptionFrame(text="Hello MediVoice", user_id="caller", timestamp="2026-11-25T10:00:00Z"),
            FrameDirection.DOWNSTREAM,
        )
        await assistant_obs.process_frame(LLMFullResponseStartFrame(), FrameDirection.DOWNSTREAM)
        await assistant_obs.process_frame(LLMTextFrame(text="Hello! "), FrameDirection.DOWNSTREAM)
        await assistant_obs.process_frame(LLMTextFrame(text="How can I help?"), FrameDirection.DOWNSTREAM)
        await assistant_obs.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)

    asyncio.run(_run())

    assert len(record.transcript) == 2
    assert record.transcript[0]["role"] == "user"
    assert record.transcript[0]["text"] == "Hello MediVoice"
    assert record.transcript[1]["role"] == "assistant"
    assert record.transcript[1]["text"] == "Hello! How can I help?"
    assert record.transcript[1]["final"] is True
    assert mock_conn.send_app_message.call_count >= 3


def test_transcript_repro_yes_followed_by_unrelated_speech_still_books(isolated_db):
    """
    Regression test reproducing the real transcript:
    9022301782 -> No -> corrected to 9022301782 -> 'Yes, it is correct.'
    followed by unrelated speech ('Is my appointment booked or not?').
    Booking must succeed when caller affirmed after readback.
    """
    db, _ = isolated_db
    state = VoiceConversationState()
    monday = next_weekday(0).isoformat()

    # Step 7-9: First number rejected with "No"
    state.record_user_turn("9022301782", turn_id="user-1")
    tool_confirm_phone_number(state, "9022301782", caller_confirmed=False)
    state.record_user_turn("No", turn_id="user-2")
    rejected = tool_book_appointment(
        state=state,
        doctor_id=1,
        patient_phone_number="9022301782",
        appointment_date=monday,
        appointment_time="10:00",
        db=db,
    )
    assert rejected["success"] is False

    # Step 11-12: Caller corrects number, assistant stages readback
    state.record_user_turn("9123456789, wait 9022301782", turn_id="user-3")
    staged = tool_confirm_phone_number(state, "9022301782", caller_confirmed=False)
    assert staged["confirmed"] is False

    # Step 13: Caller says "Yes, it is correct."
    state.record_user_turn("Yes, it is correct.", turn_id="user-4")

    # Step 14: Subsequent unrelated utterance arrives before tool executes
    state.record_user_turn("Who has your appointment schedule? Is my appointment booked or not?", turn_id="user-5")

    # Even if Gemini calls confirm_phone_number or book_appointment directly after unrelated speech,
    # the captured explicit affirmative from turn-4 remains valid!
    confirmed = tool_confirm_phone_number(state, "+919022301782", caller_confirmed=True)
    assert confirmed["confirmed"] is True

    booked = tool_book_appointment(
        state=state,
        doctor_id=1,
        patient_phone_number="+919022301782",
        appointment_date=monday,
        appointment_time="10:00",
        db=db,
    )
    assert booked["success"] is True
    assert booked["appointment"]["status"] == "booked"

    # Lookup immediately reflects the persisted DB booking
    listed = tool_list_appointments(state=state, patient_phone_number="+919022301782", db=db)
    assert listed["success"] is True
    assert listed["total"] == 1


def test_direct_book_appointment_after_explicit_affirmative(isolated_db):
    """If Gemini skips confirm_phone_number(true) and calls book_appointment after 'Yes', it succeeds."""
    db, _ = isolated_db
    state = VoiceConversationState()
    monday = next_weekday(0).isoformat()

    state.record_user_turn("9022301782", turn_id="user-1")
    tool_confirm_phone_number(state, "9022301782", caller_confirmed=False)
    state.record_user_turn("Yes, it is correct.", turn_id="user-2")

    booked = tool_book_appointment(
        state=state,
        doctor_id=1,
        patient_phone_number="+919022301782",
        appointment_date=monday,
        appointment_time="10:20",
        db=db,
    )
    assert booked["success"] is True
    assert booked["appointment"]["appointment_time"] == "10:20"


def test_booking_failure_communicated_truthfully(isolated_db):
    """Unavailable slot or duplicate booking returns success=False with a readable error."""
    db, _ = isolated_db
    state = VoiceConversationState()
    monday = next_weekday(0).isoformat()

    state.record_user_turn("9022301782", turn_id="user-1")
    tool_confirm_phone_number(state, "9022301782", caller_confirmed=False)
    state.record_user_turn("Yes", turn_id="user-2")

    first = tool_book_appointment(
        state=state,
        doctor_id=1,
        patient_phone_number="+919022301782",
        appointment_date=monday,
        appointment_time="10:40",
        db=db,
    )
    assert first["success"] is True

    duplicate = tool_book_appointment(
        state=state,
        doctor_id=1,
        patient_phone_number="+919022301782",
        appointment_date=monday,
        appointment_time="10:40",
        db=db,
    )
    assert duplicate["success"] is False
    assert duplicate["error_code"] == "duplicate_booking"
    assert "already booked" in duplicate["error"].lower()


