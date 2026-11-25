"use client";

import { Activity, ShieldCheck } from "lucide-react";

export default function Navbar({ isConnected, isChecking }) {
  const statusLabel = isChecking
    ? "Checking API"
    : isConnected
      ? "Backend Online"
      : "Backend Offline";

  const dotClass = isChecking
    ? "bg-amber-400"
    : isConnected
      ? "bg-teal-500"
      : "bg-slate-300";

  return (
    <header className="sticky top-0 z-20 border-b border-slate-200/80 bg-white/95 backdrop-blur-sm">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4 sm:px-6 lg:px-8">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#0F2942] text-white shadow-sm">
            <Activity className="h-5 w-5 text-teal-400" strokeWidth={2.2} />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-lg font-semibold tracking-tight text-[#0F2942]">
                MediVoice AI
              </span>
              <span className="hidden rounded-full border border-teal-200 bg-teal-50 px-2.5 py-0.5 text-xs font-medium text-teal-700 sm:inline-flex">
                Phase 1 · Foundation
              </span>
            </div>
            <p className="text-xs text-slate-500">
              Voice-Based Doctor Appointment Assistant
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="hidden items-center gap-1.5 text-xs font-medium text-slate-500 md:flex">
            <ShieldCheck className="h-4 w-4 text-teal-600" />
            <span>Separate Frontend &amp; FastAPI Architecture</span>
          </div>

          <div
            className="flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-700 transition-colors"
            aria-live="polite"
          >
            <span className={`h-2 w-2 rounded-full ${dotClass}`} />
            <span>{statusLabel}</span>
          </div>
        </div>
      </div>
    </header>
  );
}
