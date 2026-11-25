"""Reusable appointment business logic independent of FastAPI routes."""

from contextlib import contextmanager
from datetime import date, datetime, time
import re
from typing import Literal
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, joinedload

from app.database import SessionLocal
from app.models import Appointment, Doctor, Patient
from app.services.availability import (
    WEEKDAY_CODES,
    generate_time_slots,
    get_doctor_availability,
)

E164_PATTERN = re.compile(r"^\+[1-9]\d{7,14}$")
INDIAN_LOCAL_PATTERN = re.compile(r"^[6-9]\d{9}$")
INDIAN_ZERO_PREFIX_PATTERN = re.compile(r"^0([6-9]\d{9})$")
INDIAN_CC_NO_PLUS_PATTERN = re.compile(r"^91([6-9]\d{9})$")


class AppointmentServiceError(Exception):
    """Domain error carrying an HTTP status code and readable message."""

    def __init__(self, message: str, status_code: int, error_code: str):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code


@contextmanager
def _session_scope(db: Session | None):
    """Use an existing SQLAlchemy session or manage a fresh one cleanly."""
    if db is not None:
        yield db
        return

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def normalize_phone_number(raw_phone: str) -> str:
    """
    Validate and normalize spoken/typed phone numbers into canonical E.164 format.

    Examples:
    - '+91 98765-43210' -> '+919876543210'
    - '00919876543210'  -> '+919876543210'
    - '9876543210'      -> '+919876543210'
    - '+1 (415) 555-2671' -> '+14155552671'
    """
    if not isinstance(raw_phone, str):
        raise AppointmentServiceError(
            "Phone number must be a valid string.",
            status_code=422,
            error_code="invalid_phone_number",
        )

    cleaned = re.sub(r"[\s().-]+", "", raw_phone.strip())
    if not cleaned:
        raise AppointmentServiceError(
            "Phone number cannot be empty.",
            status_code=422,
            error_code="invalid_phone_number",
        )

    if cleaned.startswith("00"):
        cleaned = f"+{cleaned[2:]}"

    if cleaned.startswith("+"):
        digits_part = cleaned[1:]
        if not digits_part.isdigit() or not E164_PATTERN.match(cleaned):
            raise AppointmentServiceError(
                "Invalid international phone number format. Use e.g. +919876543210.",
                status_code=422,
                error_code="invalid_phone_number",
            )
        return cleaned

    if not cleaned.isdigit():
        raise AppointmentServiceError(
            "Phone number contains invalid characters.",
            status_code=422,
            error_code="invalid_phone_number",
        )

    if INDIAN_LOCAL_PATTERN.match(cleaned):
        return f"+91{cleaned}"

    zero_match = INDIAN_ZERO_PREFIX_PATTERN.match(cleaned)
    if zero_match:
        return f"+91{zero_match.group(1)}"

    cc_match = INDIAN_CC_NO_PLUS_PATTERN.match(cleaned)
    if cc_match:
        return f"+91{cc_match.group(1)}"

    candidate = f"+{cleaned}"
    if E164_PATTERN.match(candidate) and 10 <= len(cleaned) <= 15:
        return candidate

    raise AppointmentServiceError(
        "Invalid phone number. Please provide a valid 10-digit Indian or international number.",
        status_code=422,
        error_code="invalid_phone_number",
    )


def _parse_appointment_date(value: date | str) -> date:
    """Parse YYYY-MM-DD strings into date objects or raise 422."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError as exc:
            raise AppointmentServiceError(
                "Invalid appointment_date format. Expected YYYY-MM-DD.",
                status_code=422,
                error_code="invalid_appointment_date",
            ) from exc
    raise AppointmentServiceError(
        "Invalid appointment_date value.",
        status_code=422,
        error_code="invalid_appointment_date",
    )


def _normalize_appointment_time(value: str) -> str:
    """Validate and normalize 24-hour 'HH:MM' time string."""
    if not isinstance(value, str):
        raise AppointmentServiceError(
            "Invalid appointment_time value.",
            status_code=422,
            error_code="invalid_appointment_time",
        )

    stripped = value.strip()
    if not re.match(r"^\d{1,2}:\d{2}$", stripped):
        raise AppointmentServiceError(
            "Invalid appointment_time format. Expected 24-hour HH:MM (e.g. 10:00).",
            status_code=422,
            error_code="invalid_appointment_time",
        )

    parts = stripped.split(":")
    padded = f"{int(parts[0]):02d}:{int(parts[1]):02d}"
    try:
        time.fromisoformat(padded)
    except ValueError as exc:
        raise AppointmentServiceError(
            "Invalid appointment_time value. Hours must be 00-23 and minutes 00-59.",
            status_code=422,
            error_code="invalid_appointment_time",
        ) from exc

    return padded


def _serialize_appointment(appointment: Appointment) -> dict:
    """Convert an Appointment ORM row (with doctor and patient) to JSON-ready dict."""
    return {
        "id": appointment.id,
        "doctor_id": appointment.doctor_id,
        "doctor_name": appointment.doctor.name,
        "speciality": appointment.doctor.speciality,
        "patient_id": appointment.patient_id,
        "patient_name": appointment.patient.name,
        "patient_phone_number": appointment.patient.phone_number,
        "appointment_date": appointment.appointment_date.isoformat(),
        "appointment_time": appointment.appointment_time,
        "consultation_fee": appointment.doctor.consultation_fee,
        "status": appointment.status,
        "created_at": appointment.created_at.isoformat() if appointment.created_at else None,
    }


def check_doctor_availability(
    doctor_id: int,
    appointment_date: date | str,
    db: Session | None = None,
    current_dt: datetime | None = None,
) -> dict:
    """
    Reusable availability lookup for both REST routes and Pipecat voice tools.

    Verifies that the doctor exists and computes available 24-hour slots.
    """
    target_date = _parse_appointment_date(appointment_date)

    with _session_scope(db) as session:
        doctor = session.query(Doctor).filter(Doctor.id == doctor_id).first()
        if not doctor:
            raise AppointmentServiceError(
                f"Doctor with id {doctor_id} was not found.",
                status_code=404,
                error_code="doctor_not_found",
            )

        result = get_doctor_availability(
            db=session,
            doctor=doctor,
            target_date=target_date,
            current_dt=current_dt,
        )
        return {
            **result,
            "date": result["date"].isoformat(),
        }


def _get_or_create_patient(
    session: Session,
    normalized_phone: str,
    patient_name: str | None,
) -> Patient:
    """Find a patient by normalized phone number or create one safely."""
    clean_name = patient_name.strip() if isinstance(patient_name, str) and patient_name.strip() else None

    patient = session.query(Patient).filter(Patient.phone_number == normalized_phone).first()
    if patient:
        if clean_name and not patient.name:
            patient.name = clean_name
            session.flush()
        return patient

    patient = Patient(name=clean_name, phone_number=normalized_phone)
    session.add(patient)
    try:
        session.flush()
    except IntegrityError:
        # Handle concurrent first-time patient creation for the same phone number.
        session.rollback()
        existing = session.query(Patient).filter(Patient.phone_number == normalized_phone).first()
        if existing:
            return existing
        raise
    return patient


def book_appointment(
    doctor_id: int,
    patient_phone_number: str,
    appointment_date: date | str,
    appointment_time: str,
    patient_name: str | None = None,
    phone_number_confirmed: bool = False,
    db: Session | None = None,
    current_dt: datetime | None = None,
) -> dict:
    """
    Book a doctor appointment after validating phone confirmation, schedule, and slot availability.

    Reusable by FastAPI endpoints and Phase 4 Pipecat function calling.
    """
    normalized_phone = normalize_phone_number(patient_phone_number)
    if not phone_number_confirmed:
        raise AppointmentServiceError(
            "Phone number must be confirmed before booking an appointment.",
            status_code=400,
            error_code="phone_not_confirmed",
        )

    target_date = _parse_appointment_date(appointment_date)
    normalized_time = _normalize_appointment_time(appointment_time)
    now = current_dt or datetime.now()
    today = now.date()

    with _session_scope(db) as session:
        doctor = session.query(Doctor).filter(Doctor.id == doctor_id).first()
        if not doctor:
            raise AppointmentServiceError(
                f"Doctor with id {doctor_id} was not found.",
                status_code=404,
                error_code="doctor_not_found",
            )

        if not doctor.is_active:
            raise AppointmentServiceError(
                f"{doctor.name} is currently unavailable for appointments.",
                status_code=400,
                error_code="doctor_inactive",
            )

        if target_date < today:
            raise AppointmentServiceError(
                "Cannot book an appointment for a past date.",
                status_code=400,
                error_code="past_appointment",
            )

        day_code = WEEKDAY_CODES[target_date.weekday()]
        working_days = {day.strip() for day in doctor.available_days.split(",") if day.strip()}
        if day_code not in working_days:
            raise AppointmentServiceError(
                f"{doctor.name} does not consult on {day_code}.",
                status_code=400,
                error_code="non_working_day",
            )

        valid_slots = generate_time_slots(
            start_time=doctor.start_time,
            end_time=doctor.end_time,
            duration_minutes=doctor.slot_duration_minutes,
        )
        if normalized_time not in valid_slots:
            raise AppointmentServiceError(
                f"Time slot {normalized_time} is not available in {doctor.name}'s schedule.",
                status_code=409,
                error_code="unavailable_slot",
            )

        if target_date == today and time.fromisoformat(normalized_time) <= now.time():
            raise AppointmentServiceError(
                "Cannot book a past time slot for today.",
                status_code=400,
                error_code="past_appointment",
            )

        existing_active = (
            session.query(Appointment)
            .filter(
                Appointment.doctor_id == doctor.id,
                Appointment.appointment_date == target_date,
                Appointment.appointment_time == normalized_time,
                Appointment.status != "cancelled",
            )
            .first()
        )
        if existing_active:
            raise AppointmentServiceError(
                f"Slot {normalized_time} on {target_date.isoformat()} is already booked.",
                status_code=409,
                error_code="duplicate_booking",
            )

        try:
            patient = _get_or_create_patient(session, normalized_phone, patient_name)
            appointment = Appointment(
                patient_id=patient.id,
                doctor_id=doctor.id,
                appointment_date=target_date,
                appointment_time=normalized_time,
                status="booked",
            )
            session.add(appointment)
            session.commit()
            session.refresh(appointment)
        except IntegrityError as exc:
            session.rollback()
            raise AppointmentServiceError(
                f"Slot {normalized_time} on {target_date.isoformat()} has already been booked.",
                status_code=409,
                error_code="duplicate_booking",
            ) from exc
        except SQLAlchemyError as exc:
            session.rollback()
            raise AppointmentServiceError(
                "Unable to complete appointment booking due to a database error.",
                status_code=500,
                error_code="database_error",
            ) from exc

        return {
            "success": True,
            "message": "Appointment booked successfully",
            "appointment": {
                "id": appointment.id,
                "doctor_id": doctor.id,
                "doctor_name": doctor.name,
                "speciality": doctor.speciality,
                "patient_id": patient.id,
                "patient_name": patient.name,
                "patient_phone_number": patient.phone_number,
                "appointment_date": appointment.appointment_date.isoformat(),
                "appointment_time": appointment.appointment_time,
                "consultation_fee": doctor.consultation_fee,
                "status": appointment.status,
            },
        }


def cancel_appointment(
    appointment_id: int,
    patient_phone_number: str,
    phone_number_confirmed: bool = False,
    db: Session | None = None,
) -> dict:
    """
    Cancel a booked appointment after verifying phone confirmation and ownership.

    Preserves appointment history by updating status to 'cancelled' instead of deleting.
    """
    normalized_phone = normalize_phone_number(patient_phone_number)
    if not phone_number_confirmed:
        raise AppointmentServiceError(
            "Phone number must be confirmed before cancelling an appointment.",
            status_code=400,
            error_code="phone_not_confirmed",
        )

    with _session_scope(db) as session:
        appointment = (
            session.query(Appointment)
            .options(joinedload(Appointment.patient))
            .filter(Appointment.id == appointment_id)
            .first()
        )
        if not appointment:
            raise AppointmentServiceError(
                f"Appointment with id {appointment_id} was not found.",
                status_code=404,
                error_code="appointment_not_found",
            )

        if appointment.patient.phone_number != normalized_phone:
            raise AppointmentServiceError(
                "You are not authorized to cancel another patient's appointment.",
                status_code=403,
                error_code="forbidden_cancellation",
            )

        if appointment.status == "cancelled":
            raise AppointmentServiceError(
                "This appointment is already cancelled.",
                status_code=400,
                error_code="already_cancelled",
            )

        if appointment.status == "completed":
            raise AppointmentServiceError(
                "Completed appointments cannot be cancelled.",
                status_code=400,
                error_code="completed_appointment",
            )

        if appointment.status != "booked":
            raise AppointmentServiceError(
                "Only booked appointments can be cancelled.",
                status_code=400,
                error_code="invalid_status_transition",
            )

        try:
            appointment.status = "cancelled"
            session.commit()
            session.refresh(appointment)
        except SQLAlchemyError as exc:
            session.rollback()
            raise AppointmentServiceError(
                "Unable to cancel appointment due to a database error.",
                status_code=500,
                error_code="database_error",
            ) from exc

        return {
            "success": True,
            "message": "Appointment cancelled successfully",
            "appointment_id": appointment.id,
            "status": appointment.status,
        }


def list_appointments(
    patient_phone_number: str | None = None,
    doctor_id: int | None = None,
    appointment_date: date | str | None = None,
    status: Literal["booked", "cancelled", "completed"] | None = None,
    db: Session | None = None,
) -> dict:
    """List appointments with optional phone, doctor, date, and status filters."""
    normalized_phone = (
        normalize_phone_number(patient_phone_number)
        if patient_phone_number is not None and patient_phone_number.strip()
        else None
    )
    parsed_date = _parse_appointment_date(appointment_date) if appointment_date is not None else None

    with _session_scope(db) as session:
        query = (
            session.query(Appointment)
            .options(joinedload(Appointment.doctor), joinedload(Appointment.patient))
            .order_by(Appointment.appointment_date.asc(), Appointment.appointment_time.asc(), Appointment.id.asc())
        )

        if normalized_phone is not None:
            query = query.join(Patient).filter(Patient.phone_number == normalized_phone)
        if doctor_id is not None:
            query = query.filter(Appointment.doctor_id == doctor_id)
        if parsed_date is not None:
            query = query.filter(Appointment.appointment_date == parsed_date)
        if status is not None:
            query = query.filter(Appointment.status == status)

        rows = query.all()
        items = [_serialize_appointment(row) for row in rows]
        return {
            "total": len(items),
            "appointments": items,
        }


def get_appointment_by_id(appointment_id: int, db: Session | None = None) -> dict:
    """Fetch full details for a single appointment by ID."""
    with _session_scope(db) as session:
        appointment = (
            session.query(Appointment)
            .options(joinedload(Appointment.doctor), joinedload(Appointment.patient))
            .filter(Appointment.id == appointment_id)
            .first()
        )
        if not appointment:
            raise AppointmentServiceError(
                f"Appointment with id {appointment_id} was not found.",
                status_code=404,
                error_code="appointment_not_found",
            )
        return _serialize_appointment(appointment)
