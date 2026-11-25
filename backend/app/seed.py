"""Database table initialization and idempotent mock doctor seeding."""

from sqlalchemy.orm import Session

from app.database import Base, SessionLocal, engine
from app.models import Doctor

MOCK_DOCTORS = [
    {
        "name": "Dr. Ananya Sharma",
        "speciality": "Cardiologist",
        "qualification": "MBBS, MD Cardiology",
        "experience_years": 12,
        "consultation_fee": 700,
        "available_days": "Mon,Tue,Wed,Thu,Fri",
        "start_time": "09:00",
        "end_time": "13:00",
        "slot_duration_minutes": 20,
        "is_active": True,
    },
    {
        "name": "Dr. Rahul Mehta",
        "speciality": "Dermatologist",
        "qualification": "MBBS, MD Dermatology",
        "experience_years": 8,
        "consultation_fee": 600,
        "available_days": "Mon,Wed,Fri,Sat",
        "start_time": "10:00",
        "end_time": "14:00",
        "slot_duration_minutes": 20,
        "is_active": True,
    },
    {
        "name": "Dr. Priya Deshmukh",
        "speciality": "General Physician",
        "qualification": "MBBS, MD General Medicine",
        "experience_years": 10,
        "consultation_fee": 400,
        "available_days": "Mon,Tue,Wed,Thu,Fri,Sat",
        "start_time": "09:00",
        "end_time": "17:00",
        "slot_duration_minutes": 15,
        "is_active": True,
    },
    {
        "name": "Dr. Arjun Patil",
        "speciality": "Orthopedic",
        "qualification": "MBBS, MS Orthopedics",
        "experience_years": 9,
        "consultation_fee": 650,
        "available_days": "Tue,Thu,Fri,Sat",
        "start_time": "14:00",
        "end_time": "18:00",
        "slot_duration_minutes": 30,
        "is_active": True,
    },
    {
        "name": "Dr. Neha Kulkarni",
        "speciality": "Pediatrician",
        "qualification": "MBBS, MD Pediatrics",
        "experience_years": 7,
        "consultation_fee": 500,
        "available_days": "Mon,Tue,Wed,Thu,Fri",
        "start_time": "10:00",
        "end_time": "15:00",
        "slot_duration_minutes": 20,
        "is_active": True,
    },
    {
        "name": "Dr. Vikram Shah",
        "speciality": "Neurologist",
        "qualification": "MBBS, DM Neurology",
        "experience_years": 15,
        "consultation_fee": 900,
        "available_days": "Mon,Tue,Thu,Fri",
        "start_time": "15:00",
        "end_time": "19:00",
        "slot_duration_minutes": 30,
        "is_active": True,
    },
]


def seed_doctors(db: Session) -> int:
    """Insert missing mock doctors without duplicating existing records."""
    existing_names = {row[0] for row in db.query(Doctor.name).all()}
    inserted = 0

    for doctor_data in MOCK_DOCTORS:
        if doctor_data["name"] not in existing_names:
            db.add(Doctor(**doctor_data))
            inserted += 1

    if inserted:
        db.commit()

    return inserted


def init_db() -> int:
    """Create database tables and seed initial doctors idempotently."""
    # Import models so SQLAlchemy registers every table before create_all.
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        return seed_doctors(db)
    finally:
        db.close()


if __name__ == "__main__":
    added = init_db()
    print(f"Database initialized. Newly seeded doctors: {added}")
