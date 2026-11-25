"""Comprehensive Phase 3 tests using an isolated temporary SQLite database."""

from datetime import date, timedelta
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models import Appointment, Doctor, Patient
from app.seed import seed_doctors
from app.services.appointment_service import (
    AppointmentServiceError,
    book_appointment,
    cancel_appointment,
    check_doctor_availability,
)


def next_weekday(weekday_index: int) -> date:
    """Return the next future date matching weekday_index (0=Mon .. 6=Sun)."""
    today = date.today()
    days_ahead = (weekday_index - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return today + timedelta(days=days_ahead)


@pytest.fixture()
def test_db(tmp_path):
    """Create an isolated SQLite database for each test."""
    db_file = tmp_path / "test_medivoice.db"
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

    session = TestingSessionLocal()
    seed_doctors(session)

    yield session, TestingSessionLocal

    session.close()
    engine.dispose()


@pytest.fixture()
def client(test_db):
    """Provide a FastAPI TestClient wired to the isolated test database."""
    _session, session_factory = test_db

    def _override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_book_appointment_and_auto_create_patient(client, test_db):
    """Cases 1 & 2: Book an available slot and create the patient automatically."""
    db, _ = test_db
    target_date = next_weekday(0).isoformat()  # Monday (Dr. Ananya Sharma works Mon-Fri)

    response = client.post(
        "/api/appointments/book",
        json={
            "doctor_id": 1,
            "patient_name": "Rahul",
            "patient_phone_number": "+919876543210",
            "appointment_date": target_date,
            "appointment_time": "10:00",
            "phone_number_confirmed": True,
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    assert data["message"] == "Appointment booked successfully"
    assert data["appointment"]["doctor_name"] == "Dr. Ananya Sharma"
    assert data["appointment"]["patient_phone_number"] == "+919876543210"
    assert data["appointment"]["status"] == "booked"

    assert db.query(Patient).count() == 1
    patient = db.query(Patient).first()
    assert patient.phone_number == "+919876543210"
    assert patient.name == "Rahul"


def test_reuse_existing_patient_with_normalized_phone(client, test_db):
    """Case 3: Reuse the same patient when phone formatting varies."""
    db, _ = test_db
    monday = next_weekday(0).isoformat()
    wednesday = next_weekday(2).isoformat()

    res1 = client.post(
        "/api/appointments/book",
        json={
            "doctor_id": 1,
            "patient_phone_number": "+91 98765-43210",
            "appointment_date": monday,
            "appointment_time": "09:20",
            "phone_number_confirmed": True,
        },
    )
    res2 = client.post(
        "/api/appointments/book",
        json={
            "doctor_id": 2,
            "patient_name": "Rahul",
            "patient_phone_number": "9876543210",
            "appointment_date": wednesday,
            "appointment_time": "10:00",
            "phone_number_confirmed": True,
        },
    )

    assert res1.status_code == 201
    assert res2.status_code == 201
    assert db.query(Patient).count() == 1
    assert db.query(Appointment).count() == 2


def test_reject_booking_without_phone_confirmation(client):
    """Case 4: Booking without phone_number_confirmed=true returns 400."""
    response = client.post(
        "/api/appointments/book",
        json={
            "doctor_id": 1,
            "patient_phone_number": "+919876543210",
            "appointment_date": next_weekday(0).isoformat(),
            "appointment_time": "10:00",
            "phone_number_confirmed": False,
        },
    )
    assert response.status_code == 400
    assert "confirmed" in response.json()["detail"].lower()


def test_reject_booking_for_invalid_doctor(client):
    """Case 5: Non-existent doctor returns 404."""
    response = client.post(
        "/api/appointments/book",
        json={
            "doctor_id": 999,
            "patient_phone_number": "+919876543210",
            "appointment_date": next_weekday(0).isoformat(),
            "appointment_time": "10:00",
            "phone_number_confirmed": True,
        },
    )
    assert response.status_code == 404


def test_reject_booking_for_past_date_and_non_working_day(client):
    """Case 6 & non-working day: Past dates and non-working days return 400."""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    past_res = client.post(
        "/api/appointments/book",
        json={
            "doctor_id": 1,
            "patient_phone_number": "+919876543210",
            "appointment_date": yesterday,
            "appointment_time": "10:00",
            "phone_number_confirmed": True,
        },
    )
    assert past_res.status_code == 400

    sunday = next_weekday(6).isoformat()  # Dr. Ananya Sharma does not work on Sun
    non_work_res = client.post(
        "/api/appointments/book",
        json={
            "doctor_id": 1,
            "patient_phone_number": "+919876543210",
            "appointment_date": sunday,
            "appointment_time": "10:00",
            "phone_number_confirmed": True,
        },
    )
    assert non_work_res.status_code == 400


def test_reject_invalid_phone_and_unavailable_slot(client):
    """Invalid phone returns 422; off-schedule slot returns 409."""
    bad_phone = client.post(
        "/api/appointments/book",
        json={
            "doctor_id": 1,
            "patient_phone_number": "not-a-phone",
            "appointment_date": next_weekday(0).isoformat(),
            "appointment_time": "10:00",
            "phone_number_confirmed": True,
        },
    )
    assert bad_phone.status_code == 422

    # Dr. Ananya Sharma has 20-minute slots from 09:00-13:00; 10:05 is invalid slot
    bad_slot = client.post(
        "/api/appointments/book",
        json={
            "doctor_id": 1,
            "patient_phone_number": "+919876543210",
            "appointment_date": next_weekday(0).isoformat(),
            "appointment_time": "10:05",
            "phone_number_confirmed": True,
        },
    )
    assert bad_slot.status_code == 409


def test_prevent_duplicate_active_bookings(client):
    """Case 8: Booking an already-booked slot returns 409."""
    monday = next_weekday(0).isoformat()
    payload = {
        "doctor_id": 1,
        "patient_phone_number": "+919876543210",
        "appointment_date": monday,
        "appointment_time": "10:20",
        "phone_number_confirmed": True,
    }
    first = client.post("/api/appointments/book", json=payload)
    assert first.status_code == 201

    second_payload = {
        **payload,
        "patient_phone_number": "+919811112222",
    }
    second = client.post("/api/appointments/book", json=second_payload)
    assert second.status_code == 409


def test_list_and_get_appointments_by_phone_number(client):
    """Case 9: Filter appointments by caller phone number and get appointment details."""
    monday = next_weekday(0).isoformat()
    res_a = client.post(
        "/api/appointments/book",
        json={
            "doctor_id": 1,
            "patient_name": "Caller One",
            "patient_phone_number": "+919876543210",
            "appointment_date": monday,
            "appointment_time": "11:00",
            "phone_number_confirmed": True,
        },
    )
    res_b = client.post(
        "/api/appointments/book",
        json={
            "doctor_id": 1,
            "patient_name": "Caller Two",
            "patient_phone_number": "+14155552671",
            "appointment_date": monday,
            "appointment_time": "11:20",
            "phone_number_confirmed": True,
        },
    )
    assert res_a.status_code == 201
    assert res_b.status_code == 201

    list_res = client.get("/api/appointments", params={"patient_phone_number": "9876543210"})
    assert list_res.status_code == 200
    body = list_res.json()
    assert body["total"] == 1
    assert body["appointments"][0]["patient_phone_number"] == "+919876543210"

    appt_id = res_a.json()["appointment"]["id"]
    detail_res = client.get(f"/api/appointments/{appt_id}")
    assert detail_res.status_code == 200
    assert detail_res.json()["doctor_name"] == "Dr. Ananya Sharma"


def test_cancellation_flow_security_and_history(client, test_db):
    """Cases 10-15: Cancel validation, ownership, slot re-availability, and history preservation."""
    db, _ = test_db
    monday = next_weekday(0).isoformat()

    booked = client.post(
        "/api/appointments/book",
        json={
            "doctor_id": 1,
            "patient_phone_number": "+919876543210",
            "appointment_date": monday,
            "appointment_time": "11:40",
            "phone_number_confirmed": True,
        },
    )
    assert booked.status_code == 201
    appt_id = booked.json()["appointment"]["id"]

    # Case 11: Reject cancellation without phone confirmation
    no_confirm = client.post(
        f"/api/appointments/{appt_id}/cancel",
        json={
            "patient_phone_number": "+919876543210",
            "phone_number_confirmed": False,
        },
    )
    assert no_confirm.status_code == 400

    # Case 12: Reject cancellation using another patient's phone number
    wrong_caller = client.post(
        f"/api/appointments/{appt_id}/cancel",
        json={
            "patient_phone_number": "+919800000001",
            "phone_number_confirmed": True,
        },
    )
    assert wrong_caller.status_code == 403

    # Case 10: Successful cancellation
    cancel_ok = client.post(
        f"/api/appointments/{appt_id}/cancel",
        json={
            "patient_phone_number": "+919876543210",
            "phone_number_confirmed": True,
        },
    )
    assert cancel_ok.status_code == 200
    assert cancel_ok.json() == {
        "success": True,
        "message": "Appointment cancelled successfully",
        "appointment_id": appt_id,
        "status": "cancelled",
    }

    # Case 13: Reject cancelling an already cancelled appointment
    cancel_again = client.post(
        f"/api/appointments/{appt_id}/cancel",
        json={
            "patient_phone_number": "+919876543210",
            "phone_number_confirmed": True,
        },
    )
    assert cancel_again.status_code == 400

    # Case 14: Cancelled slot becomes available again and can be re-booked
    avail = client.get(f"/api/doctors/1/availability?date={monday}")
    assert avail.status_code == 200
    assert "11:40" in avail.json()["available_slots"]

    rebook = client.post(
        "/api/appointments/book",
        json={
            "doctor_id": 1,
            "patient_phone_number": "+919800000001",
            "appointment_date": monday,
            "appointment_time": "11:40",
            "phone_number_confirmed": True,
        },
    )
    assert rebook.status_code == 201

    # Case 15: Historical cancelled record is preserved alongside the new booking
    all_rows = db.query(Appointment).filter(Appointment.appointment_date == date.fromisoformat(monday)).all()
    assert len(all_rows) == 2
    assert {row.status for row in all_rows} == {"cancelled", "booked"}


def test_completed_appointment_cannot_be_cancelled(client, test_db):
    """Completed appointments return 400 if cancellation is attempted."""
    db, _ = test_db
    monday = next_weekday(0)
    patient = Patient(name="Done Patient", phone_number="+919812345678")
    db.add(patient)
    db.commit()
    db.refresh(patient)

    appt = Appointment(
        patient_id=patient.id,
        doctor_id=1,
        appointment_date=monday,
        appointment_time="12:00",
        status="completed",
    )
    db.add(appt)
    db.commit()
    db.refresh(appt)

    res = client.post(
        f"/api/appointments/{appt.id}/cancel",
        json={
            "patient_phone_number": "+919812345678",
            "phone_number_confirmed": True,
        },
    )
    assert res.status_code == 400


def test_direct_service_functions_for_pipecat(test_db):
    """Verify reusable Python functions work directly without FastAPI route objects."""
    db, _ = test_db
    monday = next_weekday(0).isoformat()

    avail = check_doctor_availability(doctor_id=1, appointment_date=monday, db=db)
    assert avail["doctor_name"] == "Dr. Ananya Sharma"
    assert "09:00" in avail["available_slots"]

    booked = book_appointment(
        doctor_id=1,
        patient_phone_number="+919876543210",
        appointment_date=monday,
        appointment_time="09:00",
        patient_name="Voice Caller",
        phone_number_confirmed=True,
        db=db,
    )
    assert booked["success"] is True

    cancelled = cancel_appointment(
        appointment_id=booked["appointment"]["id"],
        patient_phone_number="+919876543210",
        phone_number_confirmed=True,
        db=db,
    )
    assert cancelled["status"] == "cancelled"

    with pytest.raises(AppointmentServiceError) as exc_info:
        book_appointment(
            doctor_id=1,
            patient_phone_number="+919876543210",
            appointment_date=monday,
            appointment_time="09:00",
            phone_number_confirmed=False,
            db=db,
        )
    assert exc_info.value.status_code == 400
