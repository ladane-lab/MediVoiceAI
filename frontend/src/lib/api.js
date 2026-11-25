/**
 * Reusable REST and WebRTC signaling API helpers for the FastAPI backend.
 * All credentials remain on the backend; the browser only uses NEXT_PUBLIC_API_URL.
 */

const DEFAULT_API_URL = "http://localhost:8000";

export function getApiBaseUrl() {
  return (process.env.NEXT_PUBLIC_API_URL || DEFAULT_API_URL).replace(/\/+$/, "");
}

async function requestJson(path, options = {}) {
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    cache: "no-store",
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });

  if (response.status === 204) {
    return null;
  }

  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }

  if (!response.ok) {
    const detail = data?.detail || data?.message || `Request failed with HTTP ${response.status}`;
    throw new Error(detail);
  }

  return data;
}

export function fetchBackendHealth() {
  return requestJson("/health", { method: "GET" });
}

export function fetchVoiceStatus() {
  return requestJson("/api/voice/status", { method: "GET" });
}

export function fetchDoctors(speciality = "") {
  const params = new URLSearchParams();
  if (speciality && speciality.trim()) {
    params.set("speciality", speciality.trim());
  }
  const query = params.toString();
  return requestJson(`/api/doctors${query ? `?${query}` : ""}`, { method: "GET" });
}

export function fetchDoctorAvailability(doctorId, dateStr) {
  const params = new URLSearchParams({ date: dateStr });
  return requestJson(`/api/doctors/${doctorId}/availability?${params.toString()}`, {
    method: "GET",
  });
}

export function fetchAppointments({ patientPhoneNumber = "", status = "" } = {}) {
  const params = new URLSearchParams();
  if (patientPhoneNumber && patientPhoneNumber.trim()) {
    params.set("patient_phone_number", patientPhoneNumber.trim());
  }
  if (status && status.trim()) {
    params.set("status", status.trim());
  }
  const query = params.toString();
  return requestJson(`/api/appointments${query ? `?${query}` : ""}`, {
    method: "GET",
  });
}

export function cancelAppointment(appointmentId, { patientPhoneNumber, phoneNumberConfirmed }) {
  return requestJson(`/api/appointments/${appointmentId}/cancel`, {
    method: "POST",
    body: JSON.stringify({
      patient_phone_number: patientPhoneNumber,
      phone_number_confirmed: Boolean(phoneNumberConfirmed),
    }),
  });
}

export function bookAppointment({
  doctorId,
  patientName = "",
  patientPhoneNumber,
  appointmentDate,
  appointmentTime,
  phoneNumberConfirmed,
}) {
  return requestJson("/api/appointments/book", {
    method: "POST",
    body: JSON.stringify({
      doctor_id: doctorId,
      patient_name: patientName && patientName.trim() ? patientName.trim() : null,
      patient_phone_number: patientPhoneNumber,
      appointment_date: appointmentDate,
      appointment_time: appointmentTime,
      phone_number_confirmed: Boolean(phoneNumberConfirmed),
    }),
  });
}

export function createVoiceSession() {
  return requestJson("/api/voice/sessions", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function sendVoiceOffer(payload) {
  return requestJson("/api/voice/offer", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function sendVoiceIcePatch(payload) {
  return requestJson("/api/voice/offer", {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function fetchVoiceSessionSummary(sessionId) {
  return requestJson(`/api/voice/sessions/${sessionId}`, {
    method: "GET",
  });
}

export function endVoiceSession(sessionId, keepalive = false) {
  return fetch(`${getApiBaseUrl()}/api/voice/sessions/${sessionId}/end`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
    keepalive,
  }).then(async (res) => {
    if (!res.ok) return null;
    try {
      return await res.json();
    } catch {
      return null;
    }
  });
}
