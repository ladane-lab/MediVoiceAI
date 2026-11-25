"""REST API endpoints for booking, listing, inspecting, and cancelling appointments."""

from datetime import date
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    AppointmentBookRequest,
    AppointmentBookResponse,
    AppointmentCancelRequest,
    AppointmentCancelResponse,
    AppointmentDetailOut,
    AppointmentListResponse,
)
from app.services.appointment_service import (
    AppointmentServiceError,
    book_appointment,
    cancel_appointment,
    get_appointment_by_id,
    list_appointments,
)

router = APIRouter(prefix="/api/appointments", tags=["Appointments"])


@router.post(
    "/book",
    response_model=AppointmentBookResponse,
    status_code=status.HTTP_201_CREATED,
)
def book_appointment_endpoint(
    payload: AppointmentBookRequest,
    db: Session = Depends(get_db),
):
    """Book a doctor appointment for a confirmed caller phone number."""
    try:
        return book_appointment(
            doctor_id=payload.doctor_id,
            patient_phone_number=payload.patient_phone_number,
            appointment_date=payload.appointment_date,
            appointment_time=payload.appointment_time,
            patient_name=payload.patient_name,
            phone_number_confirmed=payload.phone_number_confirmed,
            db=db,
        )
    except AppointmentServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("", response_model=AppointmentListResponse)
def list_appointments_endpoint(
    patient_phone_number: str | None = Query(
        default=None,
        description="Filter by patient phone number (e.g. +919876543210)",
    ),
    doctor_id: int | None = Query(default=None, ge=1),
    appointment_date: date | None = Query(default=None),
    appointment_status: Literal["booked", "cancelled", "completed"] | None = Query(
        default=None,
        alias="status",
    ),
    db: Session = Depends(get_db),
):
    """List appointments with optional phone, doctor, date, and status filters."""
    try:
        return list_appointments(
            patient_phone_number=patient_phone_number,
            doctor_id=doctor_id,
            appointment_date=appointment_date,
            status=appointment_status,
            db=db,
        )
    except AppointmentServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/{appointment_id}", response_model=AppointmentDetailOut)
def get_appointment_endpoint(
    appointment_id: int,
    db: Session = Depends(get_db),
):
    """Return full appointment, doctor, and patient details by ID."""
    try:
        return get_appointment_by_id(appointment_id=appointment_id, db=db)
    except AppointmentServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/{appointment_id}/cancel", response_model=AppointmentCancelResponse)
def cancel_appointment_endpoint(
    appointment_id: int,
    payload: AppointmentCancelRequest,
    db: Session = Depends(get_db),
):
    """Cancel an existing booked appointment belonging to the confirmed phone number."""
    try:
        return cancel_appointment(
            appointment_id=appointment_id,
            patient_phone_number=payload.patient_phone_number,
            phone_number_confirmed=payload.phone_number_confirmed,
            db=db,
        )
    except AppointmentServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
