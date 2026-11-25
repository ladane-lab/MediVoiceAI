"""SQLAlchemy ORM models for doctors, patients, and appointments."""

from datetime import UTC, date, datetime
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utc_now() -> datetime:
    """Return current UTC timestamp."""
    return datetime.now(UTC)


class Doctor(Base):
    """Doctor profile and weekly clinic schedule."""

    __tablename__ = "doctors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    speciality: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    qualification: Mapped[str] = mapped_column(String(150), nullable=False)
    experience_years: Mapped[int] = mapped_column(Integer, nullable=False)
    consultation_fee: Mapped[int] = mapped_column(Integer, nullable=False)
    available_days: Mapped[str] = mapped_column(String(100), nullable=False)
    start_time: Mapped[str] = mapped_column(String(5), nullable=False)
    end_time: Mapped[str] = mapped_column(String(5), nullable=False)
    slot_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    appointments: Mapped[list["Appointment"]] = relationship(
        "Appointment",
        back_populates="doctor",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint("experience_years >= 0", name="ck_doctors_experience_non_negative"),
        CheckConstraint("consultation_fee >= 0", name="ck_doctors_fee_non_negative"),
        CheckConstraint("slot_duration_minutes > 0", name="ck_doctors_slot_duration_positive"),
    )


class Patient(Base):
    """Patient record identified uniquely by caller phone number."""

    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    appointments: Mapped[list["Appointment"]] = relationship(
        "Appointment",
        back_populates="patient",
        cascade="all, delete-orphan",
    )


class Appointment(Base):
    """Scheduled appointment linking a patient and a doctor."""

    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    patient_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    doctor_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("doctors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    appointment_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    appointment_time: Mapped[str] = mapped_column(String(5), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="booked",
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    patient: Mapped["Patient"] = relationship("Patient", back_populates="appointments")
    doctor: Mapped["Doctor"] = relationship("Doctor", back_populates="appointments")

    __table_args__ = (
        CheckConstraint(
            "status IN ('booked', 'cancelled', 'completed')",
            name="ck_appointments_status",
        ),
        Index(
            "ix_appointments_doctor_date_status",
            "doctor_id",
            "appointment_date",
            "status",
        ),
        # Prevent two active (non-cancelled) appointments for the same doctor, date, and time,
        # while allowing cancelled slots to be re-booked.
        Index(
            "uq_active_doctor_appointment_slot",
            "doctor_id",
            "appointment_date",
            "appointment_time",
            unique=True,
            sqlite_where=text("status != 'cancelled'"),
        ),
    )
