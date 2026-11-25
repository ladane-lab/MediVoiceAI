"use client";

import { useState } from "react";
import {
  AlertCircle,
  CalendarDays,
  CheckCircle2,
  Phone,
  RefreshCw,
  Search,
  XCircle,
} from "lucide-react";
import { cancelAppointment } from "@/lib/api";

const STATUS_STYLES = {
  booked: "bg-teal-50 text-teal-800 border-teal-200",
  cancelled: "bg-slate-100 text-slate-600 border-slate-200",
  completed: "bg-sky-50 text-sky-800 border-sky-200",
};

export default function AppointmentsSection({
  lookupPhone,
  appointments,
  isLoading,
  error,
  onLookupSubmit,
  onRefresh,
  onAfterCancel,
}) {
  const [phoneInput, setPhoneInput] = useState(lookupPhone || "");
  const [cancellingId, setCancellingId] = useState(null);
  const [confirmPhoneInput, setConfirmPhoneInput] = useState("");
  const [cancelBusy, setCancelBusy] = useState(false);
  const [cancelError, setCancelError] = useState("");
  const [cancelSuccess, setCancelSuccess] = useState("");

  function handleSearch(e) {
    e.preventDefault();
    setCancelSuccess("");
    setCancelError("");
    setCancellingId(null);
    onLookupSubmit(phoneInput);
  }

  function startCancelFlow(appt) {
    setCancellingId(appt.id);
    setConfirmPhoneInput(lookupPhone || phoneInput);
    setCancelError("");
    setCancelSuccess("");
  }

  async function submitCancel(apptId) {
    setCancelBusy(true);
    setCancelError("");
    try {
      await cancelAppointment(apptId, {
        patientPhoneNumber: confirmPhoneInput,
        phoneNumberConfirmed: true,
      });
      setCancellingId(null);
      setCancelSuccess(`Appointment #${apptId} cancelled successfully.`);
      await onAfterCancel?.();
    } catch (err) {
      setCancelError(err.message || "Unable to cancel appointment.");
    } finally {
      setCancelBusy(false);
    }
  }

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-xs">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-100 pb-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-teal-50 text-teal-700">
            <CalendarDays className="h-5 w-5" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-[#0F2942]">
              Appointments Lookup
            </h2>
            <p className="text-xs text-slate-500">
              Demo mode without login — look up appointments by your phone number
            </p>
          </div>
        </div>

        {lookupPhone ? (
          <button
            type="button"
            onClick={onRefresh}
            disabled={isLoading}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-[#0F2942] hover:bg-slate-50 disabled:opacity-60"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${isLoading ? "animate-spin" : ""}`} />
            Refresh
          </button>
        ) : null}
      </div>

      {/* Phone-number lookup form */}
      <form onSubmit={handleSearch} className="mt-4 flex flex-wrap gap-2.5">
        <div className="relative min-w-[240px] flex-1">
          <Phone className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            type="tel"
            value={phoneInput}
            onChange={(e) => setPhoneInput(e.target.value)}
            placeholder="Enter phone number (e.g. +919876543210)"
            aria-label="Caller phone number for appointment lookup"
            className="w-full rounded-xl border border-slate-200 bg-slate-50/60 py-2.5 pr-3 pl-9 text-sm text-[#0F2942] outline-none transition-colors focus:border-teal-500 focus:bg-white"
          />
        </div>

        <button
          type="submit"
          disabled={isLoading || !phoneInput.trim()}
          className="inline-flex items-center gap-2 rounded-xl bg-[#0F2942] px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-[#173a5e] disabled:cursor-not-allowed disabled:bg-slate-300"
        >
          <Search className="h-4 w-4" />
          Find Appointments
        </button>
      </form>

      {cancelSuccess ? (
        <div className="mt-4 flex items-center gap-2 rounded-xl border border-teal-200 bg-teal-50 px-4 py-3 text-xs font-medium text-teal-800">
          <CheckCircle2 className="h-4 w-4 shrink-0 text-teal-600" />
          <span>{cancelSuccess}</span>
        </div>
      ) : null}

      {error ? (
        <div className="mt-4 flex items-start gap-2.5 rounded-xl border border-rose-200 bg-rose-50 p-4 text-xs text-rose-800">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-rose-600" />
          <p>{error}</p>
        </div>
      ) : isLoading ? (
        <div className="mt-4 space-y-2.5">
          {[1, 2].map((idx) => (
            <div
              key={idx}
              className="h-20 animate-pulse rounded-xl border border-slate-200 bg-slate-100/70"
            />
          ))}
        </div>
      ) : !lookupPhone ? (
        <div className="mt-4 rounded-xl border border-dashed border-slate-200 bg-slate-50/70 p-6 text-center">
          <p className="text-sm font-medium text-slate-600">
            Enter a phone number above to view matching appointments
          </p>
          <p className="mt-1 text-xs text-slate-500">
            Only appointments registered to the entered phone number are displayed.
          </p>
        </div>
      ) : appointments.length === 0 ? (
        <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-6 text-center text-sm text-slate-500">
          No appointments found for <span className="font-mono font-medium">{lookupPhone}</span>.
        </div>
      ) : (
        <div className="mt-5 space-y-3">
          {appointments.map((appt) => {
            const isCancelling = cancellingId === appt.id;
            const statusClass = STATUS_STYLES[appt.status] || STATUS_STYLES.booked;

            return (
              <div
                key={appt.id}
                className="rounded-xl border border-slate-200 bg-slate-50/50 p-4 transition-colors hover:bg-white"
              >
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="text-sm font-semibold text-[#0F2942]">
                        {appt.doctor_name}
                      </h3>
                      <span
                        className={`rounded-full border px-2.5 py-0.5 text-[11px] font-medium capitalize ${statusClass}`}
                      >
                        {appt.status}
                      </span>
                    </div>
                    <p className="mt-0.5 text-xs text-slate-600">
                      {appt.speciality} · ₹{appt.consultation_fee} · Appointment #{appt.id}
                    </p>
                  </div>

                  <div className="flex flex-wrap items-center gap-3">
                    <div className="text-right font-mono text-xs text-[#0F2942]">
                      <p className="font-semibold">{appt.appointment_date}</p>
                      <p className="text-slate-500">{appt.appointment_time}</p>
                    </div>

                    {appt.status === "booked" && !isCancelling ? (
                      <button
                        type="button"
                        onClick={() => startCancelFlow(appt)}
                        className="inline-flex items-center gap-1 rounded-lg border border-rose-200 bg-white px-3 py-1.5 text-xs font-medium text-rose-700 hover:bg-rose-50"
                      >
                        <XCircle className="h-3.5 w-3.5" />
                        Cancel
                      </button>
                    ) : null}
                  </div>
                </div>

                {isCancelling ? (
                  <div className="mt-3 rounded-xl border border-rose-200 bg-rose-50/60 p-3.5">
                    <p className="text-xs font-medium text-rose-900">
                      Confirm phone number to cancel Appointment #{appt.id} ({appt.doctor_name} on{" "}
                      {appt.appointment_date} at {appt.appointment_time}):
                    </p>
                    <div className="mt-2.5 flex flex-wrap items-center gap-2">
                      <input
                        type="tel"
                        value={confirmPhoneInput}
                        onChange={(e) => setConfirmPhoneInput(e.target.value)}
                        placeholder="Confirm phone number"
                        className="min-w-[200px] flex-1 rounded-lg border border-rose-200 bg-white px-3 py-1.5 text-xs text-[#0F2942] outline-none focus:border-rose-400"
                      />
                      <button
                        type="button"
                        onClick={() => submitCancel(appt.id)}
                        disabled={cancelBusy || !confirmPhoneInput.trim()}
                        className="rounded-lg bg-rose-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-rose-700 disabled:opacity-60"
                      >
                        {cancelBusy ? "Cancelling..." : "Confirm Cancellation"}
                      </button>
                      <button
                        type="button"
                        onClick={() => setCancellingId(null)}
                        disabled={cancelBusy}
                        className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
                      >
                        Keep Booking
                      </button>
                    </div>
                    {cancelError ? (
                      <p className="mt-2 text-xs text-rose-700">{cancelError}</p>
                    ) : null}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
