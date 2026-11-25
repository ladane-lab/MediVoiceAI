"""Gemini function-calling tools with code-enforced confirmation state."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
import logging
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

logger = logging.getLogger(__name__)

NEGATIVE_OR_HESITATION_PATTERN = re.compile(
    r"\b(no|nope|nah|not right|not correct|not that|not this|wrong|incorrect|mistake|change|repeat|wait|hold on|stop|don't|dont|do not|never mind|nevermind|instead)\b",
    re.IGNORECASE,
)

AFFIRMATIVE_PATTERN = re.compile(
    r"\b(yes|yeah|yep|yup|correct|right|confirm|confirmed|sure|okay|ok|proceed|go ahead|please do|do it|cancel it|that is right|that's right|thats right|that is correct|that's correct|thats correct|haan|ha|sahi|bilkul|theek hai)\b",
    re.IGNORECASE,
)

PHONE_CANDIDATE_PATTERN = re.compile(r"(?:\+?\d[\d\s()-]{8,18}\d)")


def is_explicit_affirmative(utterance: str) -> bool:
    """
    Return True only when the caller uttered a clear affirmative response
    without any negative, hesitation, or correction words.
    """
    cleaned = utterance.strip()
    if not cleaned:
        return False
    if NEGATIVE_OR_HESITATION_PATTERN.search(cleaned):
        return False
    return bool(AFFIRMATIVE_PATTERN.search(cleaned))


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
    tool execution requires both a staged readback AND an explicit affirmative
    caller transcript recorded after that readback.
    """

    turn_index: int = 0
    last_user_utterance: str = ""
    last_user_turn_index: int = 0

    pending_phone_number: str | None = None
    pending_phone_turn: int | None = None
    pending_phone_affirmed_turn: int | None = None
    confirmed_phone_number: str | None = None
    phone_confirmed_turn: int | None = None

    pending_cancellation_id: int | None = None
    pending_cancellation_turn: int | None = None
    pending_cancellation_affirmed_turn: int | None = None
    confirmed_cancellation_id: int | None = None

    def record_user_turn(self, utterance: str, turn_id: str | None = None) -> None:
        """Advance conversation turn when non-empty caller speech arrives."""
        cleaned = utterance.strip()
        if not cleaned:
            return

        self.turn_index += 1
        self.last_user_utterance = cleaned
        self.last_user_turn_index = self.turn_index

        rejected = bool(NEGATIVE_OR_HESITATION_PATTERN.search(cleaned))
        affirmed = is_explicit_affirmative(cleaned)

        # Check if the caller spoke a new phone number.
        spoken_normalized: str | None = None
        match = PHONE_CANDIDATE_PATTERN.search(cleaned)
        if match:
            try:
                spoken_normalized = normalize_phone_number(match.group(0))
            except AppointmentServiceError:
                spoken_normalized = None

        # Changing the phone number invalidates prior phone and cancellation confirmations.
        if spoken_normalized:
            if self.confirmed_phone_number and spoken_normalized != self.confirmed_phone_number:
                self.confirmed_phone_number = None
                self.phone_confirmed_turn = None
                self.pending_phone_number = None
                self.pending_phone_turn = None
                self.pending_phone_affirmed_turn = None
                self.pending_cancellation_id = None
                self.pending_cancellation_turn = None
                self.pending_cancellation_affirmed_turn = None
                self.confirmed_cancellation_id = None
            elif self.pending_phone_number and spoken_normalized != self.pending_phone_number:
                self.pending_phone_number = None
                self.pending_phone_turn = None
                self.pending_phone_affirmed_turn = None

        # If caller explicitly rejects or hesitates, clear active pending gates.
        if rejected:
            if self.pending_phone_number and not self.confirmed_phone_number:
                self.pending_phone_number = None
                self.pending_phone_turn = None
                self.pending_phone_affirmed_turn = None
            if self.pending_cancellation_id and not self.confirmed_cancellation_id:
                self.pending_cancellation_id = None
                self.pending_cancellation_turn = None
                self.pending_cancellation_affirmed_turn = None
        elif affirmed:
            # Capture explicit affirmative immediately while a readback is awaiting confirmation
            # so a subsequent unrelated follow-up question does not erase the affirmative.
            if (
                self.pending_phone_number is not None
                and self.pending_phone_turn is not None
                and self.turn_index > self.pending_phone_turn
                and self.confirmed_phone_number != self.pending_phone_number
            ):
                self.pending_phone_affirmed_turn = self.turn_index

            if (
                self.pending_cancellation_id is not None
                and self.pending_cancellation_turn is not None
                and self.turn_index > self.pending_cancellation_turn
                and self.confirmed_cancellation_id != self.pending_cancellation_id
            ):
                self.pending_cancellation_affirmed_turn = self.turn_index

        logger.info(
            "Voice turn recorded: turn_id=%s turn_index=%d pending_phone=%s confirmed_phone=%s affirmed=%s rejected=%s",
            turn_id or "n/a",
            self.turn_index,
            bool(self.pending_phone_number),
            bool(self.confirmed_phone_number),
            affirmed,
            rejected,
        )

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

        # Preserve existing staged readback if caller already has this exact number pending
        # and we are waiting on or have already captured their post-readback affirmative.
        if (
            self.pending_phone_number == normalized
            and self.pending_phone_turn is not None
            and self.pending_phone_affirmed_turn is not None
            and self.pending_phone_affirmed_turn > self.pending_phone_turn
        ):
            self.confirmed_phone_number = normalized
            self.phone_confirmed_turn = self.pending_phone_affirmed_turn
            return {
                "success": True,
                "confirmed": True,
                "phone_number": normalized,
                "digit_by_digit": format_phone_digit_by_digit(normalized),
                "message": "Phone number confirmed by caller.",
            }

        self.pending_phone_number = normalized
        self.pending_phone_turn = self.turn_index
        self.pending_phone_affirmed_turn = None
        self.confirmed_phone_number = None
        self.phone_confirmed_turn = None
        # Changing caller phone invalidates any prior cancellation approval.
        self.pending_cancellation_id = None
        self.pending_cancellation_turn = None
        self.pending_cancellation_affirmed_turn = None
        self.confirmed_cancellation_id = None

        spoken_digits = format_phone_digit_by_digit(normalized)
        logger.info("Staged phone number for confirmation at turn_index=%d", self.turn_index)
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
        """
        Confirm a staged phone number only when grounded in an explicit
        affirmative caller transcript after digit-by-digit readback.
        """
        normalized = normalize_phone_number(raw_phone)

        if self.is_phone_confirmed(normalized):
            return {
                "success": True,
                "confirmed": True,
                "phone_number": normalized,
                "message": (
                    "Phone number confirmed. If doctor, date, and time are already selected, "
                    "call book_appointment now."
                ),
            }

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

        if self.last_user_turn_index <= self.pending_phone_turn:
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

        if self.pending_phone_affirmed_turn is None or self.pending_phone_affirmed_turn <= self.pending_phone_turn:
            if NEGATIVE_OR_HESITATION_PATTERN.search(self.last_user_utterance):
                self.pending_phone_number = None
                self.pending_phone_turn = None
                self.pending_phone_affirmed_turn = None
                self.confirmed_phone_number = None
                self.phone_confirmed_turn = None
                return {
                    "success": False,
                    "confirmed": False,
                    "message": "Caller indicated the phone number was incorrect. Ask them to repeat it.",
                }

            spoken_digits = format_phone_digit_by_digit(normalized)
            return {
                "success": False,
                "confirmed": False,
                "phone_number": normalized,
                "digit_by_digit": spoken_digits,
                "message": (
                    f"Caller has not explicitly confirmed {spoken_digits}. "
                    "Ask them to say yes or confirm if the number is correct."
                ),
            }

        self.confirmed_phone_number = normalized
        self.phone_confirmed_turn = self.pending_phone_affirmed_turn
        logger.info(
            "Phone confirmation succeeded at turn_index=%d (affirmed_turn=%d)",
            self.turn_index,
            self.phone_confirmed_turn,
        )
        return {
            "success": True,
            "confirmed": True,
            "phone_number": normalized,
            "message": (
                "Phone number confirmed. If doctor, date, and time are already selected, "
                "call book_appointment now."
            ),
        }

    def try_resolve_pending_phone_confirmation(self, normalized_phone: str) -> bool:
        """
        Promote a staged phone number to confirmed if the caller has already
        spoken an explicit affirmative after readback.
        """
        if self.is_phone_confirmed(normalized_phone):
            return True
        if (
            self.pending_phone_number == normalized_phone
            and self.pending_phone_turn is not None
            and self.pending_phone_affirmed_turn is not None
            and self.pending_phone_affirmed_turn > self.pending_phone_turn
        ):
            self.confirmed_phone_number = normalized_phone
            self.phone_confirmed_turn = self.pending_phone_affirmed_turn
            logger.info(
                "Auto-promoted affirmed phone confirmation at turn_index=%d (affirmed_turn=%d)",
                self.turn_index,
                self.phone_confirmed_turn,
            )
            return True
        return False

    def stage_cancellation(self, appointment_id: int, appointment_summary: dict[str, Any]) -> dict[str, Any]:
        """Stage an appointment for explicit caller cancellation confirmation."""
        self.pending_cancellation_id = appointment_id
        self.pending_cancellation_turn = self.turn_index
        self.pending_cancellation_affirmed_turn = None
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
        """
        Approve cancellation only when appointment details were read back and
        followed by an explicit affirmative caller response.
        """
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

        if self.last_user_turn_index <= self.pending_cancellation_turn:
            return {
                "success": False,
                "cancellation_confirmed": False,
                "message": (
                    "Wait for the caller to respond after reading back the appointment details "
                    "before confirming cancellation."
                ),
            }

        if (
            self.pending_cancellation_affirmed_turn is None
            or self.pending_cancellation_affirmed_turn <= self.pending_cancellation_turn
        ):
            if NEGATIVE_OR_HESITATION_PATTERN.search(self.last_user_utterance):
                self.pending_cancellation_id = None
                self.pending_cancellation_turn = None
                self.pending_cancellation_affirmed_turn = None
                self.confirmed_cancellation_id = None
                return {
                    "success": False,
                    "cancellation_confirmed": False,
                    "message": "Caller declined cancellation. Keep the appointment booked.",
                }
            return {
                "success": False,
                "cancellation_confirmed": False,
                "message": (
                    "Caller has not explicitly confirmed cancellation. "
                    "Ask them to clearly confirm with yes before cancelling."
                ),
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
    logger.info(
        "confirm_phone_number invoked: caller_confirmed=%s turn_index=%d pending=%s",
        bool(caller_confirmed),
        state.turn_index,
        bool(state.pending_phone_number),
    )
    try:
        result = state.confirm_phone(raw_phone=phone_number, caller_confirmed=bool(caller_confirmed))
        logger.info(
            "confirm_phone_number result: success=%s confirmed=%s",
            result.get("success"),
            result.get("confirmed"),
        )
        return result
    except AppointmentServiceError as exc:
        logger.warning("confirm_phone_number error: error_code=%s", exc.error_code)
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
    logger.info(
        "book_appointment invoked: doctor_id=%s date=%s time=%s turn_index=%d confirmed_phone=%s",
        doctor_id,
        appointment_date,
        appointment_time,
        state.turn_index,
        bool(state.confirmed_phone_number),
    )
    try:
        normalized_phone = normalize_phone_number(patient_phone_number)
    except AppointmentServiceError as exc:
        logger.warning("book_appointment invalid phone: error_code=%s", exc.error_code)
        return _safe_error(exc.message, exc.error_code)

    if not state.try_resolve_pending_phone_confirmation(normalized_phone):
        # Do not clobber an active pending readback for the same phone number on the same turn.
        if state.pending_phone_number == normalized_phone and state.pending_phone_turn is not None:
            spoken_digits = format_phone_digit_by_digit(normalized_phone)
            return {
                "success": False,
                "requires_phone_confirmation": True,
                "phone_number": normalized_phone,
                "digit_by_digit": spoken_digits,
                "error": (
                    f"Phone number is not confirmed yet. Repeat {spoken_digits} "
                    "digit by digit, ask the caller to confirm, and wait for yes."
                ),
                "error_code": "phone_not_confirmed",
            }

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
        result = service_book_appointment(
            doctor_id=int(doctor_id),
            patient_phone_number=normalized_phone,
            appointment_date=appointment_date,
            appointment_time=appointment_time,
            patient_name=patient_name,
            phone_number_confirmed=True,
            db=db,
        )
        appt = result.get("appointment") or {}
        logger.info(
            "book_appointment persisted: appointment_id=%s doctor_id=%s date=%s time=%s status=%s",
            appt.get("id"),
            appt.get("doctor_id"),
            appt.get("appointment_date"),
            appt.get("appointment_time"),
            appt.get("status"),
        )
        return result
    except AppointmentServiceError as exc:
        logger.warning(
            "book_appointment service rejected: doctor_id=%s date=%s time=%s error_code=%s",
            doctor_id,
            appointment_date,
            appointment_time,
            exc.error_code,
        )
        return _safe_error(exc.message, exc.error_code)
    except (TypeError, ValueError):
        logger.warning("book_appointment invalid arguments")
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

    if not state.try_resolve_pending_phone_confirmation(normalized_phone):
        if state.pending_phone_number == normalized_phone and state.pending_phone_turn is not None:
            spoken_digits = format_phone_digit_by_digit(normalized_phone)
            return {
                "success": False,
                "requires_phone_confirmation": True,
                "phone_number": normalized_phone,
                "digit_by_digit": spoken_digits,
                "error": (
                    f"Phone number must be confirmed before looking up appointments. Repeat "
                    f"{spoken_digits} digit by digit and ask the caller to confirm."
                ),
                "error_code": "phone_not_confirmed",
            }
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
        if caller_confirmed and NEGATIVE_OR_HESITATION_PATTERN.search(state.last_user_utterance):
            return {
                "success": False,
                "cancellation_confirmed": False,
                "message": "Caller declined cancellation. Keep the appointment booked.",
            }
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
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> ToolsSchema:
    """Create Pipecat FunctionSchemas bound to the session's confirmation state."""

    def _run_with_session(fn, **kwargs):
        db = db_session_factory()
        try:
            return fn(db=db, **kwargs)
        finally:
            db.close()

    def _emit(payload: dict[str, Any]) -> None:
        if on_event is not None:
            on_event(payload)

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
        logger.info(
            "Returning confirm_phone_number result to Gemini: success=%s confirmed=%s",
            result.get("success"),
            result.get("confirmed"),
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
        logger.info(
            "Returning book_appointment result to Gemini: success=%s error_code=%s",
            result.get("success"),
            result.get("error_code"),
        )
        if result.get("success"):
            _emit(
                {
                    "type": "appointment_updated",
                    "action": "booked",
                    "appointment": result.get("appointment"),
                }
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
        if result.get("success"):
            _emit(
                {
                    "type": "appointment_updated",
                    "action": "cancelled",
                    "appointment_id": result.get("appointment_id"),
                }
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
