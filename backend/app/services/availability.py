"""Reusable dynamic slot availability calculation for doctors."""

from datetime import date, datetime, time, timedelta
from sqlalchemy.orm import Session

from app.models import Appointment, Doctor

WEEKDAY_CODES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def generate_time_slots(start_time: str, end_time: str, duration_minutes: int) -> list[str]:
    """Generate 24-hour 'HH:MM' slots within [start_time, end_time]."""
    if duration_minutes <= 0:
        return []

    start_dt = datetime.combine(date.today(), time.fromisoformat(start_time))
    end_dt = datetime.combine(date.today(), time.fromisoformat(end_time))
    step = timedelta(minutes=duration_minutes)

    slots: list[str] = []
    current = start_dt
    while current + step <= end_dt:
        slots.append(current.strftime("%H:%M"))
        current += step

    return slots


def get_doctor_availability(
    db: Session,
    doctor: Doctor,
    target_date: date,
    current_dt: datetime | None = None,
) -> dict:
    """
    Calculate available 24-hour slots for a doctor on a given date.

    Rules enforced:
    - Inactive doctors have no available slots.
    - Past dates and past times for today are never offered.
    - Doctor's configured working days are respected.
    - Active appointments ('booked', 'completed') block their slot.
    - Cancelled appointments ('cancelled') free their slot again.
    """
    now = current_dt or datetime.now()
    today = now.date()
    day_code = WEEKDAY_CODES[target_date.weekday()]
    working_days = {day.strip() for day in doctor.available_days.split(",") if day.strip()}
    is_working_day = day_code in working_days

    base_payload = {
        "doctor_id": doctor.id,
        "doctor_name": doctor.name,
        "speciality": doctor.speciality,
        "consultation_fee": doctor.consultation_fee,
        "date": target_date,
        "day_of_week": day_code,
        "is_working_day": is_working_day,
        "slot_duration_minutes": doctor.slot_duration_minutes,
    }

    if not doctor.is_active:
        return {
            **base_payload,
            "available_slots": [],
            "total_available": 0,
            "message": "Doctor is currently unavailable for appointments.",
        }

    if target_date < today:
        return {
            **base_payload,
            "available_slots": [],
            "total_available": 0,
            "message": "Past dates cannot be booked.",
        }

    if not is_working_day:
        return {
            **base_payload,
            "available_slots": [],
            "total_available": 0,
            "message": f"{doctor.name} does not consult on {day_code}.",
        }

    all_slots = generate_time_slots(
        start_time=doctor.start_time,
        end_time=doctor.end_time,
        duration_minutes=doctor.slot_duration_minutes,
    )

    occupied_rows = (
        db.query(Appointment.appointment_time)
        .filter(
            Appointment.doctor_id == doctor.id,
            Appointment.appointment_date == target_date,
            Appointment.status != "cancelled",
        )
        .all()
    )
    occupied_slots = {row[0] for row in occupied_rows}

    available_slots: list[str] = []
    for slot in all_slots:
        if slot in occupied_slots:
            continue
        if target_date == today and time.fromisoformat(slot) <= now.time():
            continue
        available_slots.append(slot)

    message = None if available_slots else "No available slots remaining for this date."
    return {
        **base_payload,
        "available_slots": available_slots,
        "total_available": len(available_slots),
        "message": message,
    }
