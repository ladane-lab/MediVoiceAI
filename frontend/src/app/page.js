"use client";

import { useCallback, useEffect, useState } from "react";
import { Stethoscope, Cpu, AudioLines, Database } from "lucide-react";
import Navbar from "@/components/Navbar";
import BackendHealthCard from "@/components/BackendHealthCard";
import PhaseRoadmap from "@/components/PhaseRoadmap";
import { fetchBackendHealth, getApiBaseUrl } from "@/lib/api";

const STACK_PILLARS = [
  {
    title: "Frontend Interface",
    value: "Next.js · React · Tailwind",
    icon: Stethoscope,
  },
  {
    title: "Voice & WebRTC",
    value: "Pipecat · ElevenLabs STT/TTS",
    icon: AudioLines,
  },
  {
    title: "Clinical Reasoning",
    value: "Google Gemini LLM",
    icon: Cpu,
  },
  {
    title: "Backend & Storage",
    value: "FastAPI · SQLite",
    icon: Database,
  },
];

export default function Home() {
  const [health, setHealth] = useState(null);
  const [error, setError] = useState("");
  const [isChecking, setIsChecking] = useState(true);

  const apiUrl = getApiBaseUrl();

  const handleRefresh = useCallback(async () => {
    setIsChecking(true);
    setError("");
    try {
      const data = await fetchBackendHealth();
      setHealth(data);
    } catch (err) {
      setHealth(null);
      setError(err instanceof Error ? err.message : "Connection failed");
    } finally {
      setIsChecking(false);
    }
  }, []);

  useEffect(() => {
    let active = true;

    fetchBackendHealth()
      .then((data) => {
        if (!active) return;
        setHealth(data);
        setError("");
      })
      .catch((err) => {
        if (!active) return;
        setHealth(null);
        setError(err instanceof Error ? err.message : "Connection failed");
      })
      .finally(() => {
        if (active) setIsChecking(false);
      });

    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="flex min-h-screen flex-col bg-slate-50">
      <Navbar isConnected={Boolean(health)} isChecking={isChecking} />

      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6 lg:px-8">
        {/* Hero Overview Banner */}
        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-xs sm:p-8">
          <div className="max-w-3xl">
            <span className="inline-flex items-center rounded-full bg-[#0F2942]/5 px-3 py-1 text-xs font-semibold text-[#0F2942]">
              Healthcare SaaS Workspace · Phase 1 Setup
            </span>
            <h1 className="mt-3 text-2xl font-semibold tracking-tight text-[#0F2942] sm:text-3xl">
              MediVoice AI — Voice-Based Doctor Appointment Assistant
            </h1>
            <p className="mt-2.5 text-sm leading-relaxed text-slate-600 sm:text-base">
              Phase 1 establishes the decoupled frontend and Python backend
              foundation. Appointment scheduling flows and the real-time Pipecat
              WebRTC voice assistant will be connected in subsequent phases.
            </p>
          </div>

          <div className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {STACK_PILLARS.map((item) => {
              const Icon = item.icon;
              return (
                <div
                  key={item.title}
                  className="rounded-xl border border-slate-200/80 bg-slate-50/70 p-4 transition-colors hover:border-teal-200 hover:bg-teal-50/20"
                >
                  <div className="flex items-center gap-2 text-teal-700">
                    <Icon className="h-4 w-4" />
                    <span className="text-xs font-medium text-slate-500">
                      {item.title}
                    </span>
                  </div>
                  <p className="mt-1.5 text-sm font-semibold text-[#0F2942]">
                    {item.value}
                  </p>
                </div>
              );
            })}
          </div>
        </section>

        {/* Health Check + Phase Roadmap */}
        <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
          <BackendHealthCard
            apiUrl={apiUrl}
            health={health}
            error={error}
            isChecking={isChecking}
            onRefresh={handleRefresh}
          />
          <PhaseRoadmap />
        </div>
      </main>

      <footer className="border-t border-slate-200/80 bg-white py-4">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-2 px-4 text-xs text-slate-500 sm:px-6 lg:px-8">
          <span>MediVoice AI · Phase 1 Foundation</span>
          <span>Next.js (JSX) + FastAPI + Pipecat Architecture</span>
        </div>
      </footer>
    </div>
  );
}
