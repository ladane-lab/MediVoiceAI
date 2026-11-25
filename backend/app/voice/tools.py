"""Gemini function-calling tools with code-enforced confirmation state."""

import asyncio
from dataclasses import dataclass, field
import re
from typing import Any
from sqlalchemy.orm import Session

from pipecat.adapters.llm.schemas.function_schema import FunctionSchema
from pipecat.adapters.llm.schemas.tools_schema import ToolsSchema
from pipecat.services.llm_service import FunctionCallParams

from app.database import SessionLocal
from app.models import Doctor
from app.services.appointment_service import (
    AppointmentServiceError,
    book_appointment as service_book_appointment,
    cancel_appointment as service_cancel_appointment,
    check_doctor_availability as service_check_doctor_availability,
    get_appointment_by_id,
    list_appointments as service_list_appointments,
    normalize_phone_number,
)

REJECTION_PATTERN = re.compile(
    r"\b(no|nope|wrong|incorrect|not right|nah|mistake|change it|repeat)\b",
    re.IGNORECASE,
)


def format_phone_digit_by_digit(normalized_phone: str) -> str:
    """Format an E.164 phone number into spoken digit-by-digit text."""
    return " ".join(
        "plus" if ch == "+" else ch
        for ch in normalized_phone
    )


@dataclass
class VoiceConversationState:
    """
    Per-call state machine enforcing caller confirmation gates in Python code.

    Gemini cannot skip phone confirmation or cancellation confirmation because
    tool execution checks this state before invoking Phase 3 write/lookup services.
    """

    turn_index: int = 0
    last_user_utterance: str = ""

    pending_phone_number: str | None = None
    pending_phone_turn: int | None = None
    confirmed_phone_number: str | None = None

    pending_cancellation_id: int | None = None
    pending_cancellation_turn: int | None = None
    confirmed_cancellation_id: int | None = None

    def record_user_turn(self, utterance: str) -> None:
        """Advance conversation turn when the caller speaks."""
        self.turn_index += 1
        self.last_user_utterance = utterance.strip()

        # If caller explicitly rejects during an active confirmation step, reset gates.
        if REJECTION_PATTERN.search(self.last_user_utterance):
            if self.pending_phone_number and not self.confirmed_phone_number:
                self.pending_phone_number = None
                self.pending_phone_turn = None
            if self.pending_cancellation_id and not self.confirmed_cancellation_id:
                self.pending_cancellation_id = None
                self.pending_cancellation_turn = None

    def is_phone_confirmed(self, normalized_phone: str) -> bool:
        """Return True only when the exact normalized phone number is confirmed."""
        return (
            self.confirmed_phone_number is not None
            and self.confirmed_phone_number == normalized_phone
        )

    def is_cancellation_confirmed(self, appointment_id: int) -> bool:
        """Return True only when cancellation of appointment_id was explicitly confirmed."""
        return (
            self.confirmed_cancellation_id is not None
            and self.confirmed_cancellation_id == appointment_id
        )

    def stage_phone_number(self, raw_phone: str) -> dict[str, Any]:
        """Normalize and stage a phone number for digit-by-digit caller confirmation."""
        normalized = normalize_phone_number(raw_phone)
        if self.confirmed_phone_number == normalized:
            return {
                "success": True,
                "confirmed": True,
                "phone_number": normalized,
                "digit_by_digit": format_phone_digit_by_digit(normalized),
                "message": "Phone number is already confirmed.",
            }

        self.pending_phone_number = normalized
        self.pending_phone_turn = self.turn_index
        self.confirmed_phone_number = None
        # Changing caller phone invalidates any prior cancellation approval.
        self.pending_cancellation_id = None
        self.pending_cancellation_turn = None
        self.confirmed_cancellation_id = None

        spoken_digits = format_phone_digit_by_digit(normalized)
        return {
            "success": True,
            "confirmed": False,
            "phone_number": normalized,
            "digit_by_digit": spoken_digits,
            "message": (
                f"Repeat the phone number digit by digit ({spoken_digits}) and ask "
                "the caller to confirm before proceeding."
            ),
        }

    def confirm_phone(self, raw_phone: str, caller_confirmed: bool) -> dict[str, Any]:
        """Confirm a staged phone number only after a subsequent caller turn."""
        normalized = normalize_phone_number(raw_phone)

        if not caller_confirmed:
            staged = self.stage_phone_number(normalized)
            return {
                **staged,
                "message": (
                    "Caller has not confirmed yet. Read back the digits and ask "
                    "the caller to repeat if incorrect."
                ),
            }

        if self.pending_phone_number != normalized or self.pending_phone_turn is None:
            return self.stage_phone_number(normalized)

        if self.turn_index <= self.pending_phone_turn:
            spoken_digits = format_phone_digit_by_digit(normalized)
            return {
                "success": False,
                "confirmed": False,
                "phone_number": normalized,
                "digit_by_digit": spoken_digits,
                "message": (
                    f"Wait for the caller to confirm after repeating {spoken_digits} "
                    "digit by digit before calling confirm_phone_number with caller_confirmed=true."
                ),
            }

        if REJECTION_PATTERN.search(self.last_user_utterance):
            self.pending_phone_number = None
            self.pending_phone_turn = None
            self.confirmed_phone_number = None
            return {
                "success": False,
                "confirmed": False,
                "message": "Caller indicated the phone number was incorrect. Ask them to repeat it.",
            }

        self.confirmed_phone_number = normalized
        return {
            "success": True,
            "confirmed": True,
            "phone_number": normalized,
            "message": "Phone number confirmed.",
        }

    def stage_cancellation(self, appointment_id: int, appointment_summary: dict[str, Any]) -> dict[str, Any]:
        """Stage an appointment for explicit caller cancellation confirmation."""
        self.pending_cancellation_id = appointment_id
        self.pending_cancellation_turn = self.turn_index
        self.confirmed_cancellation_id = None
        return {
            "success": False,
            "cancellation_confirmed": False,
            "requires_cancellation_confirmation": True,
            "appointment": appointment_summary,
            "message": (
                f"Read the appointment details back (Appointment #{appointment_id} with "
                f"{appointment_summary['doctor_name']} on {appointment_summary['appointment_date']} "
                f"at {appointment_summary['appointment_time']}) and ask the caller to explicitly "
                "confirm cancellation."
            ),
        }

    def confirm_cancellation(self, appointment_id: int, caller_confirmed: bool) -> dict[str, Any]:
        """Approve cancellation only after appointment details were read back and confirmed."""
        if not caller_confirmed:
            self.confirmed_cancellation_id = None
            return {
                "success": False,
                "cancellation_confirmed": False,
                "message": "Caller has not confirmed cancellation yet. Ask for explicit confirmation.",
            }

        if self.pending_cancellation_id != appointment_id or self.pending_cancellation_turn is None:
            return {
                "success": False,
                "cancellation_confirmed": False,
                "message": (
                    "Read the appointment details back to the caller first, then ask for "
                    "explicit confirmation before confirming cancellation."
                ),
            }

        if self.turn_index <= self.pending_cancellation_turn:
            return {
                "success": False,
                "cancellation_confirmed": False,
                "message": (
                    "Wait for the caller to respond after reading back the appointment details "
                    "before confirming cancellation."
                ),
            }

        if REJECTION_PATTERN.search(self.last_user_utterance):
            self.pending_cancellation_id = None
            self.pending_cancellation_turn = None
            self.confirmed_cancellation_id = None
            return {
                "success": False,
                "cancellation_confirmed": False,
                "message": "Caller declined cancellation. Keep the appointment booked.",
            }

        self.confirmed_cancellation_id = appointment_id
        return {
            "success": True,
            "cancellation_confirmed": True,
            "appointment_id": appointment_id,
            "message": "Cancellation explicitly confirmed by caller.",
        }


def _safe_error(message: str, error_code: str = "tool_error") -> dict[str, Any]:
    return {"success": False, "error": message, "error_code": error_code}


def tool_list_doctors(
    speciality: str | None = None,
    db: Session | None = None,
) -> dict[str, Any]:
    """Return active doctors and their schedule/fee metadata from SQLite."""
    owns_session = db is None
    session = db or SessionLocal()
    try:
        query = session.query(Doctor).filter(Doctor.is_active.is_(True)).order_by(Doctor.id.asc())
        if speciality and speciality.strip():
            query = query.filter(Doctor.speciality.ilike(f"%{speciality.strip()}%"))

        doctors = query.all()
        items = [
            {
                "id": doc.id,
                "name": doc.name,
                "speciality": doc.speciality,
                "qualification": doc.qualification,
                "experience_years": doc.experience_years,
                "consultation_fee": doc.consultation_fee,
                "available_days": [d.strip() for d in doc.available_days.split(",") if d.strip()],
                "start_time": doc.start_time,
                "end_time": doc.end_time,
                "slot_duration_minutes": doc.slot_duration_minutes,
            }
            for doc in doctors
        ]
        return {"success": True, "total": len(items), "doctors": items}
    except Exception:
        return _safe_error("Unable to retrieve doctor list right now.", "database_error")
    finally:
        if owns_session:
            session.close()


def tool_check_doctor_availability(
    doctor_id: int,
    appointment_date: str,
    db: Session | None = None,
) -> dict[str, Any]:
    """Check available 24-hour slots for a doctor on a YYYY-MM-DD date."""
    try:
        result = service_check_doctor_availability(
            doctor_id=int(doctor_id),
            appointment_date=appointment_date,
            db=db,
        )
        return {"success": True, **result}
    except AppointmentServiceError as exc:
        return _safe_error(exc.message, exc.error_code)
    except (TypeError, ValueError):
        return _safe_error("doctor_id must be a valid integer.", "invalid_arguments")


def tool_confirm_phone_number(
    state: VoiceConversationState,
    phone_number: str,
    caller_confirmed: bool = False,
) -> dict[str, Any]:
    """Enforce digit-by-digit phone confirmation before booking, listing, or cancelling."""
    try:
        return state.confirm_phone(raw_phone=phone_number, caller_confirmed=bool(caller_confirmed))
    except AppointmentServiceError as exc:
        return _safe_error(exc.message, exc.error_code)


def tool_book_appointment(
    state: VoiceConversationState,
    doctor_id: int,
    patient_phone_number: str,
    appointment_date: str,
    appointment_time: str,
    patient_name: str | None = None,
    db: Session | None = None,
) -> dict[str, Any]:
    """Book an appointment only if the caller's phone number is confirmed in state."""
    try:
        normalized_phone = normalize_phone_number(patient_phone_number)
    except AppointmentServiceError as exc:
        return _safe_error(exc.message, exc.error_code)

    if not state.is_phone_confirmed(normalized_phone):
        staged = state.stage_phone_number(normalized_phone)
        return {
            "success": False,
            "requires_phone_confirmation": True,
            "phone_number": staged["phone_number"],
            "digit_by_digit": staged["digit_by_digit"],
            "error": (
                f"Phone number is not confirmed yet. Repeat {staged['digit_by_digit']} "
                "digit by digit, ask the caller to confirm, and call confirm_phone_number "
                "after they respond."
            ),
            "error_code": "phone_not_confirmed",
        }

    try:
        return service_book_appointment(
            doctor_id=int(doctor_id),
            patient_phone_number=normalized_phone,
            appointment_date=appointment_date,
            appointment_time=appointment_time,
            patient_name=patient_name,
            phone_number_confirmed=True,
            db=db,
        )
    except AppointmentServiceError as exc:
        return _safe_error(exc.message, exc.error_code)
    except (TypeError, ValueError):
        return _safe_error("Invalid booking arguments provided.", "invalid_arguments")


def tool_list_appointments(
    state: VoiceConversationState,
    patient_phone_number: str,
    db: Session | None = None,
) -> dict[str, Any]:
    """Look up appointments only after the caller's phone number is confirmed in state."""
    try:
        normalized_phone = normalize_phone_number(patient_phone_number)
    except AppointmentServiceError as exc:
        return _safe_error(exc.message, exc.error_code)

    if not state.is_phone_confirmed(normalized_phone):
        staged = state.stage_phone_number(normalized_phone)
        return {
            "success": False,
            "requires_phone_confirmation": True,
            "phone_number": staged["phone_number"],
            "digit_by_digit": staged["digit_by_digit"],
            "error": (
                f"Phone number must be confirmed before looking up appointments. Repeat "
                f"{staged['digit_by_digit']} digit by digit and ask the caller to confirm."
            ),
            "error_code": "phone_not_confirmed",
        }

    try:
        result = service_list_appointments(patient_phone_number=normalized_phone, db=db)
        return {"success": True, **result}
    except AppointmentServiceError as exc:
        return _safe_error(exc.message, exc.error_code)


def tool_confirm_cancellation(
    state: VoiceConversationState,
    appointment_id: int,
    patient_phone_number: str,
    caller_confirmed: bool = False,
    db: Session | None = None,
) -> dict[str, Any]:
    """Enforce readback + explicit cancellation confirmation before cancelling."""
    try:
        normalized_phone = normalize_phone_number(patient_phone_number)
        appt_id = int(appointment_id)
    except AppointmentServiceError as exc:
        return _safe_error(exc.message, exc.error_code)
    except (TypeError, ValueError):
        return _safe_error("appointment_id must be a valid integer.", "invalid_arguments")

    if not state.is_phone_confirmed(normalized_phone):
        staged = state.stage_phone_number(normalized_phone)
        return {
            "success": False,
            "requires_phone_confirmation": True,
            "digit_by_digit": staged["digit_by_digit"],
            "error": "Confirm the caller's phone number digit by digit first.",
            "error_code": "phone_not_confirmed",
        }

    try:
        appt = get_appointment_by_id(appointment_id=appt_id, db=db)
    except AppointmentServiceError as exc:
        return _safe_error(exc.message, exc.error_code)

    if appt["patient_phone_number"] != normalized_phone:
        return _safe_error(
            "You are not authorized to access or cancel another patient's appointment.",
            "forbidden_cancellation",
        )

    if appt["status"] != "booked":
        return _safe_error(
            f"Appointment #{appt_id} cannot be cancelled because its status is '{appt['status']}'.",
            "invalid_status_transition",
        )

    if state.pending_cancellation_id != appt_id:
        return state.stage_cancellation(appt_id, appt)

    return state.confirm_cancellation(appt_id, bool(caller_confirmed))


def tool_cancel_appointment(
    state: VoiceConversationState,
    appointment_id: int,
    patient_phone_number: str,
    db: Session | None = None,
) -> dict[str, Any]:
    """Cancel an appointment only after BOTH phone and cancellation confirmations."""
    try:
        normalized_phone = normalize_phone_number(patient_phone_number)
        appt_id = int(appointment_id)
    except AppointmentServiceError as exc:
        return _safe_error(exc.message, exc.error_code)
    except (TypeError, ValueError):
        return _safe_error("appointment_id must be a valid integer.", "invalid_arguments")

    if not state.is_phone_confirmed(normalized_phone):
        staged = state.stage_phone_number(normalized_phone)
        return {
            "success": False,
            "requires_phone_confirmation": True,
            "digit_by_digit": staged["digit_by_digit"],
            "error": (
                f"Phone number must be confirmed first. Repeat {staged['digit_by_digit']} "
                "digit by digit and ask the caller to confirm."
            ),
            "error_code": "phone_not_confirmed",
        }

    if not state.is_cancellation_confirmed(appt_id):
        try:
            appt = get_appointment_by_id(appointment_id=appt_id, db=db)
        except AppointmentServiceError as exc:
            return _safe_error(exc.message, exc.error_code)

        if appt["patient_phone_number"] != normalized_phone:
            return _safe_error(
                "You are not authorized to cancel another patient's appointment.",
                "forbidden_cancellation",
            )
        if appt["status"] != "booked":
            return _safe_error(
                f"Appointment #{appt_id} cannot be cancelled because its status is '{appt['status']}'.",
                "invalid_status_transition",
            )
        return state.stage_cancellation(appt_id, appt)

    try:
        result = service_cancel_appointment(
            appointment_id=appt_id,
            patient_phone_number=normalized_phone,
            phone_number_confirmed=True,
            db=db,
        )
        state.pending_cancellation_id = None
        state.pending_cancellation_turn = None
        state.confirmed_cancellation_id = None
        return result
    except AppointmentServiceError as exc:
        return _safe_error(exc.message, exc.error_code)


def build_voice_tools(
    state: VoiceConversationState,
    db_session_factory=SessionLocal,
) -> ToolsSchema:
    """Create Pipecat FunctionSchemas bound to the session's confirmation state."""

    def _run_with_session(fn, **kwargs):
        db = db_session_factory()
        try:
            return fn(db=db, **kwargs)
        finally:
            db.close()

    async def handle_list_doctors(params: FunctionCallParams):
        args = dict(params.arguments or {})
        result = await asyncio.to_thread(
            _run_with_session,
            tool_list_doctors,
            speciality=args.get("speciality"),
        )
        await params.result_callback(result)

    async def handle_check_availability(params: FunctionCallParams):
        args = dict(params.arguments or {})
        result = await asyncio.to_thread(
            _run_with_session,
            tool_check_doctor_availability,
            doctor_id=args.get("doctor_id"),
            appointment_date=args.get("appointment_date", ""),
        )
        await params.result_callback(result)

    async def handle_confirm_phone(params: FunctionCallParams):
        args = dict(params.arguments or {})
        result = await asyncio.to_thread(
            tool_confirm_phone_number,
            state=state,
            phone_number=args.get("phone_number", ""),
            caller_confirmed=bool(args.get("caller_confirmed", False)),
        )
        await params.result_callback(result)

    async def handle_book_appointment(params: FunctionCallParams):
        args = dict(params.arguments or {})
        result = await asyncio.to_thread(
            _run_with_session,
            tool_book_appointment,
            state=state,
            doctor_id=args.get("doctor_id"),
            patient_phone_number=args.get("patient_phone_number", ""),
            appointment_date=args.get("appointment_date", ""),
            appointment_time=args.get("appointment_time", ""),
            patient_name=args.get("patient_name"),
        )
        await params.result_callback(result)

    async def handle_list_appointments(params: FunctionCallParams):
        args = dict(params.arguments or {})
        result = await asyncio.to_thread(
            _run_with_session,
            tool_list_appointments,
            state=state,
            patient_phone_number=args.get("patient_phone_number", ""),
        )
        await params.result_callback(result)

    async def handle_confirm_cancellation(params: FunctionCallParams):
        args = dict(params.arguments or {})
        result = await asyncio.to_thread(
            _run_with_session,
            tool_confirm_cancellation,
            state=state,
            appointment_id=args.get("appointment_id"),
            patient_phone_number=args.get("patient_phone_number", ""),
            caller_confirmed=bool(args.get("caller_confirmed", False)),
        )
        await params.result_callback(result)

    async def handle_cancel_appointment(params: FunctionCallParams):
        args = dict(params.arguments or {})
        result = await asyncio.to_thread(
            _run_with_session,
            tool_cancel_appointment,
            state=state,
            appointment_id=args.get("appointment_id"),
            patient_phone_number=args.get("patient_phone_number", ""),
        )
        await params.result_callback(result)

    schemas = [
        FunctionSchema(
            name="list_doctors",
            description="List available doctors, their speciality, experience, consultation fee, working days, and ID.",
            properties={
                "speciality": {
                    "type": "string",
                    "description": "Optional medical speciality filter (e.g. Cardiologist, Dermatologist).",
                }
            },
            required=[],
            handler=handle_list_doctors,
        ),
        FunctionSchema(
            name="check_doctor_availability",
            description="Check available 24-hour appointment time slots for a specific doctor on a given date.",
            properties={
                "doctor_id": {"type": "integer", "description": "Numeric ID of the doctor."},
                "appointment_date": {
                    "type": "string",
                    "description": "Appointment date in YYYY-MM-DD format.",
                },
            },
            required=["doctor_id", "appointment_date"],
            handler=handle_check_availability,
        ),
        FunctionSchema(
            name="confirm_phone_number",
            description=(
                "Stage a caller's phone number for digit-by-digit readback (caller_confirmed=false), "
                "or confirm it after the caller explicitly agrees it is correct (caller_confirmed=true)."
            ),
            properties={
                "phone_number": {
                    "type": "string",
                    "description": "Phone number spoken by the caller, including country code such as +91.",
                },
                "caller_confirmed": {
                    "type": "boolean",
                    "description": "Set true only AFTER repeating the number digit by digit and hearing the caller confirm.",
                },
            },
            required=["phone_number", "caller_confirmed"],
            handler=handle_confirm_phone,
        ),
        FunctionSchema(
            name="book_appointment",
            description="Book an appointment after the caller has confirmed their phone number, doctor, date, and time.",
            properties={
                "doctor_id": {"type": "integer", "description": "Numeric ID of the doctor."},
                "patient_phone_number": {
                    "type": "string",
                    "description": "Confirmed caller phone number (e.g. +919876543210).",
                },
                "patient_name": {
                    "type": "string",
                    "description": "Optional patient name.",
                },
                "appointment_date": {
                    "type": "string",
                    "description": "Appointment date in YYYY-MM-DD format.",
                },
                "appointment_time": {
                    "type": "string",
                    "description": "24-hour slot time in HH:MM format (e.g. 10:00).",
                },
            },
            required=["doctor_id", "patient_phone_number", "appointment_date", "appointment_time"],
            handler=handle_book_appointment,
        ),
        FunctionSchema(
            name="list_appointments",
            description="Look up appointments belonging to a caller's confirmed phone number.",
            properties={
                "patient_phone_number": {
                    "type": "string",
                    "description": "Confirmed caller phone number.",
                },
            },
            required=["patient_phone_number"],
            handler=handle_list_appointments,
        ),
        FunctionSchema(
            name="confirm_cancellation",
            description=(
                "Read back an appointment and stage it for cancellation (caller_confirmed=false), "
                "or record explicit cancellation approval after the caller confirms (caller_confirmed=true)."
            ),
            properties={
                "appointment_id": {"type": "integer", "description": "Appointment ID to cancel."},
                "patient_phone_number": {
                    "type": "string",
                    "description": "Confirmed caller phone number.",
                },
                "caller_confirmed": {
                    "type": "boolean",
                    "description": "Set true only AFTER reading back appointment details and receiving explicit approval.",
                },
            },
            required=["appointment_id", "patient_phone_number", "caller_confirmed"],
            handler=handle_confirm_cancellation,
        ),
        FunctionSchema(
            name="cancel_appointment",
            description="Cancel a booked appointment after both phone number and cancellation have been confirmed.",
            properties={
                "appointment_id": {"type": "integer", "description": "Appointment ID to cancel."},
                "patient_phone_number": {
                    "type": "string",
                    "description": "Confirmed caller phone number.",
                },
            },
            required=["appointment_id", "patient_phone_number"],
            handler=handle_cancel_appointment,
        ),
    ]

    return ToolsSchema(standard_tools=schemas)
