"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Sidebar from "@/components/Sidebar";
import Navbar from "@/components/Navbar";
import SummaryCards from "@/components/SummaryCards";
import VoiceAssistantCard from "@/components/VoiceAssistantCard";
import DoctorsSection from "@/components/DoctorsSection";
import AppointmentsSection from "@/components/AppointmentsSection";
import useVoiceCall from "@/hooks/useVoiceCall";
import {
  fetchAppointments,
  fetchBackendHealth,
  fetchDoctors,
  fetchVoiceStatus,
} from "@/lib/api";

export default function Home() {
  const [activeTab, setActiveTab] = useState("dashboard");
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const [isBackendOnline, setIsBackendOnline] = useState(false);
  const [isCheckingBackend, setIsCheckingBackend] = useState(true);
  const [voiceStatus, setVoiceStatus] = useState(null);

  const [doctors, setDoctors] = useState([]);
  const [doctorsLoading, setDoctorsLoading] = useState(true);
  const [doctorsError, setDoctorsError] = useState("");
  const [availabilityRefreshTick, setAvailabilityRefreshTick] = useState(0);

  const [lookupPhone, setLookupPhone] = useState("");
  const [appointments, setAppointments] = useState([]);
  const [appointmentsLoading, setAppointmentsLoading] = useState(false);
  const [appointmentsError, setAppointmentsError] = useState("");

  const loadDoctors = useCallback(async () => {
    setDoctorsLoading(true);
    setDoctorsError("");
    try {
      const data = await fetchDoctors();
      setDoctors(data.doctors || []);
    } catch (err) {
      setDoctorsError(err.message || "Unable to load doctors.");
    } finally {
      setDoctorsLoading(false);
    }
  }, []);

  const loadAppointments = useCallback(async (phone) => {
    const cleaned = (phone || "").trim();
    if (!cleaned) {
      setAppointments([]);
      setAppointmentsError("");
      return;
    }

    setAppointmentsLoading(true);
    setAppointmentsError("");
    try {
      const data = await fetchAppointments({ patientPhoneNumber: cleaned });
      setAppointments(data.appointments || []);
    } catch (err) {
      setAppointments([]);
      setAppointmentsError(err.message || "Unable to load appointments.");
    } finally {
      setAppointmentsLoading(false);
    }
  }, []);

  const handleVoiceAppointmentUpdated = useCallback(
    (event) => {
      setAvailabilityRefreshTick((prev) => prev + 1);
      const bookedPhone = event?.appointment?.patient_phone_number;
      const phoneToQuery = bookedPhone || lookupPhone;
      if (bookedPhone && !lookupPhone) {
        setLookupPhone(bookedPhone);
      }
      if (phoneToQuery) {
        loadAppointments(phoneToQuery);
      }
    },
    [loadAppointments, lookupPhone],
  );

  const remoteAudioRef = useRef(null);

  const attachRemoteStream = useCallback((stream) => {
    const el = remoteAudioRef.current;
    if (!el) return;
    el.srcObject = stream;
    el.muted = false;
    el.volume = 1.0;
  }, []);

  const playRemoteAudio = useCallback(() => {
    const el = remoteAudioRef.current;
    if (!el) return Promise.resolve();
    el.muted = false;
    el.volume = 1.0;
    return el.play();
  }, []);

  const clearRemoteStream = useCallback(() => {
    const el = remoteAudioRef.current;
    if (!el) return;
    el.srcObject = null;
  }, []);

  const voiceCall = useVoiceCall({
    onAttachRemoteStream: attachRemoteStream,
    onPlayRemoteAudio: playRemoteAudio,
    onClearRemoteStream: clearRemoteStream,
    onAppointmentUpdated: handleVoiceAppointmentUpdated,
  });

  useEffect(() => {
    let active = true;

    Promise.allSettled([fetchBackendHealth(), fetchVoiceStatus(), fetchDoctors()])
      .then(([healthRes, voiceRes, docsRes]) => {
        if (!active) return;

        if (healthRes.status === "fulfilled") {
          setIsBackendOnline(healthRes.value?.status === "ok");
        } else {
          setIsBackendOnline(false);
        }

        if (voiceRes.status === "fulfilled") {
          setVoiceStatus(voiceRes.value);
        }

        if (docsRes.status === "fulfilled") {
          setDoctors(docsRes.value?.doctors || []);
          setDoctorsError("");
        } else {
          setDoctorsError(docsRes.reason?.message || "Unable to load doctors.");
        }
      })
      .finally(() => {
        if (!active) return;
        setIsCheckingBackend(false);
        setDoctorsLoading(false);
      });

    return () => {
      active = false;
    };
  }, []);

  const handleManualAppointmentBooked = useCallback(
    async (bookedPhone) => {
      setAvailabilityRefreshTick((prev) => prev + 1);
      const targetPhone = (bookedPhone || lookupPhone || "").trim();
      if (targetPhone) {
        setLookupPhone(targetPhone);
        await loadAppointments(targetPhone);
      }
    },
    [loadAppointments, lookupPhone],
  );

  function handleLookupSubmit(phone) {
    const cleaned = phone.trim();
    setLookupPhone(cleaned);
    loadAppointments(cleaned);
  }

  function handleStartCallFromDoctor() {
    setActiveTab("voice");
    if (
      voiceCall.status === "idle" ||
      voiceCall.status === "ended" ||
      voiceCall.status === "error"
    ) {
      voiceCall.startCall();
    }
  }

  return (
    <div className="flex min-h-screen bg-slate-50 text-[#0F2942]">
      {/* Persistent remote audio element so active WebRTC audio continues across tab switches */}
      <audio ref={remoteAudioRef} autoPlay playsInline className="hidden" />

      <Sidebar
        activeTab={activeTab}
        onSelectTab={setActiveTab}
        voiceCallStatus={voiceCall.status}
        mobileOpen={mobileMenuOpen}
        onCloseMobile={() => setMobileMenuOpen(false)}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        <Navbar
          activeTab={activeTab}
          isBackendOnline={isBackendOnline}
          isCheckingBackend={isCheckingBackend}
          isVoiceReady={Boolean(voiceStatus?.ready)}
          onOpenMobileMenu={() => setMobileMenuOpen(true)}
        />

        <main className="mx-auto w-full max-w-7xl flex-1 space-y-6 px-4 py-6 sm:px-6 lg:px-8">
          {activeTab === "dashboard" ? (
            <>
              {/* Welcome Banner */}
              <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-xs">
                <div className="flex flex-wrap items-center justify-between gap-4">
                  <div className="max-w-2xl">
                    <span className="inline-flex items-center rounded-full bg-teal-50 px-3 py-1 text-xs font-semibold text-teal-700">
                      Voice-Based Appointment Assistant
                    </span>
                    <h2 className="mt-2.5 text-xl font-semibold tracking-tight text-[#0F2942] sm:text-2xl">
                      Welcome to MediVoice AI
                    </h2>
                    <p className="mt-1.5 text-sm text-slate-600">
                      Speak naturally with MediVoice AI over WebRTC to check doctor
                      availability, book appointments, or cancel existing bookings.
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => setActiveTab("doctors")}
                      className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-medium text-[#0F2942] hover:bg-slate-50"
                    >
                      Browse Doctors
                    </button>
                    <button
                      type="button"
                      onClick={() => setActiveTab("appointments")}
                      className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-medium text-[#0F2942] hover:bg-slate-50"
                    >
                      Lookup by Phone
                    </button>
                  </div>
                </div>
              </section>

              <SummaryCards
                doctorsCount={doctorsLoading ? null : doctors.length}
                voiceReady={Boolean(voiceStatus?.ready)}
                callStatus={voiceCall.status}
                appointments={appointments}
                lookupPhone={lookupPhone}
              />

              <VoiceAssistantCard voiceCall={voiceCall} voiceStatus={voiceStatus} />

              <DoctorsSection
                doctors={doctors}
                isLoading={doctorsLoading}
                error={doctorsError}
                onRefresh={loadDoctors}
                availabilityRefreshTick={availabilityRefreshTick}
                onStartVoiceCall={handleStartCallFromDoctor}
                onAppointmentBooked={handleManualAppointmentBooked}
              />

              <AppointmentsSection
                lookupPhone={lookupPhone}
                appointments={appointments}
                isLoading={appointmentsLoading}
                error={appointmentsError}
                onLookupSubmit={handleLookupSubmit}
                onRefresh={() => loadAppointments(lookupPhone)}
                onAfterCancel={async () => {
                  await loadAppointments(lookupPhone);
                  setAvailabilityRefreshTick((prev) => prev + 1);
                }}
              />
            </>
          ) : null}

          {activeTab === "doctors" ? (
            <DoctorsSection
              doctors={doctors}
              isLoading={doctorsLoading}
              error={doctorsError}
              onRefresh={loadDoctors}
              availabilityRefreshTick={availabilityRefreshTick}
              onStartVoiceCall={handleStartCallFromDoctor}
              onAppointmentBooked={handleManualAppointmentBooked}
            />
          ) : null}

          {activeTab === "appointments" ? (
            <AppointmentsSection
              lookupPhone={lookupPhone}
              appointments={appointments}
              isLoading={appointmentsLoading}
              error={appointmentsError}
              onLookupSubmit={handleLookupSubmit}
              onRefresh={() => loadAppointments(lookupPhone)}
              onAfterCancel={async () => {
                await loadAppointments(lookupPhone);
                setAvailabilityRefreshTick((prev) => prev + 1);
              }}
            />
          ) : null}

          {activeTab === "voice" ? (
            <VoiceAssistantCard
              voiceCall={voiceCall}
              voiceStatus={voiceStatus}
              expanded
            />
          ) : null}
        </main>
      </div>
    </div>
  );
}
