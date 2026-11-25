"""Pydantic schemas for request validation and clean JSON API responses."""

from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class DoctorOut(BaseModel):
    """Public doctor profile and clinic schedule."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    speciality: str
    qualification: str
    experience_years: int
    consultation_fee: int
    available_days: list[str]
    start_time: str
    end_time: str
    slot_duration_minutes: int
    is_active: bool

    @field_validator("available_days", mode="before")
    @classmethod
    def parse_available_days(cls, value):
        """Convert comma-separated weekday strings from SQLite into a list."""
        if isinstance(value, str):
            return [day.strip() for day in value.split(",") if day.strip()]
        return value


class DoctorListResponse(BaseModel):
    """Response envelope for listing doctors."""

    total: int
    doctors: list[DoctorOut]


class DoctorAvailabilityResponse(BaseModel):
    """Response schema for dynamic doctor slot availability."""

    doctor_id: int
    doctor_name: str
    speciality: str
    consultation_fee: int
    date: date
    day_of_week: str
    is_working_day: bool
    slot_duration_minutes: int
    available_slots: list[str]
    total_available: int
    message: str | None = None


class PatientOut(BaseModel):
    """Patient schema identified by phone number."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str | None = None
    phone_number: str = Field(..., min_length=8, max_length=20)
    created_at: datetime


class AppointmentOut(BaseModel):
    """Raw appointment ORM representation."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_id: int
    doctor_id: int
    appointment_date: date
    appointment_time: str
    status: Literal["booked", "cancelled", "completed"]
    created_at: datetime


class AppointmentBookRequest(BaseModel):
    """Request payload for booking an appointment."""

    doctor_id: int = Field(..., ge=1)
    patient_name: str | None = Field(default=None, max_length=120)
    patient_phone_number: str = Field(..., min_length=1, max_length=32)
    appointment_date: date
    appointment_time: str = Field(..., min_length=4, max_length=5)
    phone_number_confirmed: bool = False


class AppointmentSummary(BaseModel):
    """Appointment summary returned on booking confirmation."""

    id: int
    doctor_id: int
    doctor_name: str
    speciality: str
    patient_id: int
    patient_name: str | None = None
    patient_phone_number: str
    appointment_date: date
    appointment_time: str
    consultation_fee: int
    status: Literal["booked", "cancelled", "completed"]


class AppointmentBookResponse(BaseModel):
    """Response payload for a booked appointment."""

    success: bool
    message: str
    appointment: AppointmentSummary


class AppointmentDetailOut(AppointmentSummary):
    """Detailed appointment record including creation timestamp."""

    created_at: datetime


class AppointmentListResponse(BaseModel):
    """Response envelope for listing appointments."""

    total: int
    appointments: list[AppointmentDetailOut]


class AppointmentCancelRequest(BaseModel):
    """Request payload for cancelling an appointment."""

    patient_phone_number: str = Field(..., min_length=1, max_length=32)
    phone_number_confirmed: bool = False


class AppointmentCancelResponse(BaseModel):
    """Response payload for appointment cancellation."""

    success: bool
    message: str
    appointment_id: int
    status: Literal["cancelled"]


class VoiceStatusResponse(BaseModel):
    """Non-secret readiness report for the Pipecat WebRTC voice agent."""

    ready: bool
    transport: str
    llm_provider: str
    llm_model: str
    stt_provider: str
    tts_provider: str
    missing_env_vars: list[str]
    active_sessions: int


class VoiceSessionCreateResponse(BaseModel):
    """Response returned when pre-registering a voice session."""

    session_id: str
    status: str
    transport: str
    offer_url: str
    ice_servers: list[str]


class VoiceOfferRequest(BaseModel):
    """WebRTC SDP offer payload from the browser."""

    sdp: str = Field(..., min_length=1)
    type: Literal["offer", "answer", "pranswer", "rollback"] = "offer"
    pc_id: str | None = None
    restart_pc: bool | None = None
    session_id: str | None = None


class VoiceOfferResponse(BaseModel):
    """WebRTC SDP answer returned to complete browser peer connection."""

    sdp: str
    type: str
    pc_id: str
    session_id: str


class IceCandidatePayload(BaseModel):
    """Single WebRTC ICE candidate."""

    candidate: str
    sdp_mid: str | None = None
    sdp_mline_index: int | None = None


class VoiceIcePatchRequest(BaseModel):
    """Trickle ICE candidate update request."""

    pc_id: str = Field(..., min_length=1)
    candidates: list[IceCandidatePayload]


class VoiceSessionStateSummary(BaseModel):
    """Sanitized confirmation state summary for a voice session."""

    session_id: str
    pc_id: str | None = None
    status: str
    created_at: datetime
    phone_confirmed: bool
    pending_phone_confirmation: bool
    pending_cancellation_id: int | None = None
    error: str | None = None


class VoiceSessionEndResponse(BaseModel):
    """Response returned when ending a voice session."""

    success: bool
    session_id: str
    status: str
    message: str
