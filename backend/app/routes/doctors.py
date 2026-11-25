"""Read-only doctor directory and dynamic availability endpoints."""

from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Doctor
from app.schemas import DoctorAvailabilityResponse, DoctorListResponse, DoctorOut
from app.services.appointment_service import (
    AppointmentServiceError,
    check_doctor_availability,
)

router = APIRouter(prefix="/api/doctors", tags=["Doctors"])


@router.get("", response_model=DoctorListResponse)
def list_doctors(
    speciality: str | None = Query(default=None, description="Optional speciality filter"),
    db: Session = Depends(get_db),
):
    """Return all doctors, optionally filtered by speciality."""
    query = db.query(Doctor).order_by(Doctor.id.asc())
    if speciality:
        query = query.filter(Doctor.speciality.ilike(f"%{speciality.strip()}%"))

    doctors = query.all()
    return DoctorListResponse(total=len(doctors), doctors=doctors)


@router.get("/{doctor_id}", response_model=DoctorOut)
def get_doctor(doctor_id: int, db: Session = Depends(get_db)):
    """Return details for a single doctor by ID."""
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Doctor with id {doctor_id} was not found.",
        )
    return doctor


@router.get("/{doctor_id}/availability", response_model=DoctorAvailabilityResponse)
def get_availability(
    doctor_id: int,
    target_date: date = Query(..., alias="date", description="Date in YYYY-MM-DD format"),
    db: Session = Depends(get_db),
):
    """Return dynamically generated available slots for a doctor on a date."""
    try:
        return check_doctor_availability(
            doctor_id=doctor_id,
            appointment_date=target_date,
            db=db,
        )
    except AppointmentServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
