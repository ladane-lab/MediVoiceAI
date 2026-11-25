"use client";

import { useEffect, useState } from "react";
import {
  AlertCircle,
  Calendar,
  Clock,
  GraduationCap,
  IndianRupee,
  RefreshCw,
  Stethoscope,
} from "lucide-react";
import { fetchDoctorAvailability } from "@/lib/api";

function getTodayIso() {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export default function DoctorsSection({
  doctors,
  isLoading,
  error,
  onRefresh,
  availabilityRefreshTick = 0,
  onStartVoiceCall,
}) {
  const [selectedSpeciality, setSelectedSpeciality] = useState("All");
  const [selectedDoctor, setSelectedDoctor] = useState(null);
  const [selectedDate, setSelectedDate] = useState("");
  const [availability, setAvailability] = useState(null);
  const [availLoading, setAvailLoading] = useState(false);
  const [availError, setAvailError] = useState("");

  const specialities = [
    "All",
    ...Array.from(new Set(doctors.map((doc) => doc.speciality))),
  ];

  const filteredDoctors =
    selectedSpeciality === "All"
      ? doctors
      : doctors.filter((doc) => doc.speciality === selectedSpeciality);

  function handleSelectDoctor(doc) {
    if (!selectedDate) {
      setSelectedDate(getTodayIso());
    }
    setSelectedDoctor(doc);
    setAvailLoading(true);
    setAvailError("");
  }

  function handleDateChange(nextDate) {
    setSelectedDate(nextDate);
    if (selectedDoctor) {
      setAvailLoading(true);
      setAvailError("");
    }
  }

  useEffect(() => {
    if (!selectedDoctor || !selectedDate) return undefined;
    let active = true;

    fetchDoctorAvailability(selectedDoctor.id, selectedDate)
      .then((data) => {
        if (!active) return;
        setAvailability(data);
        setAvailError("");
      })
      .catch((err) => {
        if (!active) return;
        setAvailability(null);
        setAvailError(err.message || "Failed to load availability.");
      })
      .finally(() => {
        if (active) setAvailLoading(false);
      });

    return () => {
      active = false;
    };
  }, [selectedDoctor, selectedDate, availabilityRefreshTick]);

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-xs">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-100 pb-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-sky-50 text-sky-700">
            <Stethoscope className="h-5 w-5" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-[#0F2942]">
              Available Doctors
            </h2>
            <p className="text-xs text-slate-500">
              Select a doctor to inspect real-time slot availability
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <select
            value={selectedSpeciality}
            onChange={(e) => setSelectedSpeciality(e.target.value)}
            aria-label="Filter doctors by speciality"
            className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-[#0F2942] outline-none focus:border-teal-500"
          >
            {specialities.map((spec) => (
              <option key={spec} value={spec}>
                {spec === "All" ? "All Specialities" : spec}
              </option>
            ))}
          </select>

          <button
            type="button"
            onClick={onRefresh}
            disabled={isLoading}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-[#0F2942] transition-colors hover:bg-slate-50 disabled:opacity-60"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${isLoading ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>
      </div>

      {error ? (
        <div className="mt-4 flex items-start gap-2.5 rounded-xl border border-rose-200 bg-rose-50 p-4 text-xs text-rose-800">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-rose-600" />
          <p>{error}</p>
        </div>
      ) : isLoading ? (
        <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
          {[1, 2, 3, 4].map((idx) => (
            <div
              key={idx}
              className="h-32 animate-pulse rounded-xl border border-slate-200 bg-slate-100/70"
            />
          ))}
        </div>
      ) : filteredDoctors.length === 0 ? (
        <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-6 text-center text-sm text-slate-500">
          No doctors matched your filter.
        </div>
      ) : (
        <div className="mt-5 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {filteredDoctors.map((doc) => {
            const isSelected = selectedDoctor?.id === doc.id;
            return (
              <button
                key={doc.id}
                type="button"
                onClick={() => handleSelectDoctor(doc)}
                className={`flex flex-col justify-between rounded-xl border p-4 text-left transition-colors ${
                  isSelected
                    ? "border-teal-500 bg-teal-50/40 ring-1 ring-teal-500/30"
                    : "border-slate-200 bg-slate-50/40 hover:border-teal-300 hover:bg-white"
                }`}
              >
                <div>
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <h3 className="text-sm font-semibold text-[#0F2942]">
                        {doc.name}
                      </h3>
                      <p className="text-xs font-medium text-teal-700">
                        {doc.speciality}
                      </p>
                    </div>
                    <span className="inline-flex items-center rounded-full bg-[#0F2942]/5 px-2.5 py-0.5 text-xs font-semibold text-[#0F2942]">
                      <IndianRupee className="mr-0.5 h-3 w-3" />
                      {doc.consultation_fee}
                    </span>
                  </div>

                  <div className="mt-3 space-y-1.5 text-xs text-slate-600">
                    <p className="flex items-center gap-1.5">
                      <GraduationCap className="h-3.5 w-3.5 text-slate-400" />
                      <span>
                        {doc.qualification} · {doc.experience_years} yrs exp
                      </span>
                    </p>
                    <p className="flex items-center gap-1.5">
                      <Clock className="h-3.5 w-3.5 text-slate-400" />
                      <span>
                        {doc.start_time} – {doc.end_time} ({doc.slot_duration_minutes} min)
                      </span>
                    </p>
                  </div>
                </div>

                <div className="mt-3 flex flex-wrap gap-1">
                  {doc.available_days.map((day) => (
                    <span
                      key={day}
                      className="rounded-md border border-slate-200 bg-white px-1.5 py-0.5 text-[10px] font-medium text-slate-600"
                    >
                      {day}
                    </span>
                  ))}
                </div>
              </button>
            );
          })}
        </div>
      )}

      {/* Selected Doctor Live Availability Drawer */}
      {selectedDoctor ? (
        <div className="mt-6 rounded-xl border border-teal-200 bg-teal-50/30 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold text-[#0F2942]">
                {selectedDoctor.name} — Live Slot Availability
              </h3>
              <p className="text-xs text-slate-600">
                {selectedDoctor.speciality} · ₹{selectedDoctor.consultation_fee} consultation fee
              </p>
            </div>

            <div className="flex items-center gap-2">
              <label className="flex items-center gap-1.5 text-xs font-medium text-slate-600">
                <Calendar className="h-3.5 w-3.5 text-teal-700" />
                <input
                  type="date"
                  value={selectedDate}
                  onChange={(e) => handleDateChange(e.target.value)}
                  className="rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs text-[#0F2942] outline-none focus:border-teal-500"
                />
              </label>

              {onStartVoiceCall ? (
                <button
                  type="button"
                  onClick={onStartVoiceCall}
                  className="rounded-lg bg-[#0F2942] px-3 py-1.5 text-xs font-medium text-white hover:bg-[#173a5e]"
                >
                  Book via Voice
                </button>
              ) : null}
            </div>
          </div>

          <div className="mt-4">
            {availLoading ? (
              <p className="text-xs text-slate-500">Loading available slots...</p>
            ) : availError ? (
              <p className="text-xs text-rose-700">{availError}</p>
            ) : availability ? (
              availability.available_slots.length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  {availability.available_slots.map((slot) => (
                    <span
                      key={slot}
                      className="rounded-lg border border-teal-200 bg-white px-3 py-1.5 font-mono text-xs font-medium text-[#0F2942]"
                    >
                      {slot}
                    </span>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-slate-600">
                  {availability.message || "No available slots on this date."}
                </p>
              )
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}
