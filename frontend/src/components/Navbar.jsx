"use client";

import { Menu, ShieldCheck } from "lucide-react";

const TAB_TITLES = {
  dashboard: "Clinical Overview",
  doctors: "Find Doctors & Live Availability",
  appointments: "My Appointments",
  voice: "Voice Assistant",
};

export default function Navbar({
  activeTab,
  isBackendOnline,
  isCheckingBackend,
  isVoiceReady,
  onOpenMobileMenu,
}) {
  const apiBadgeClass = isCheckingBackend
    ? "bg-amber-50 text-amber-700 border-amber-200"
    : isBackendOnline
      ? "bg-teal-50 text-teal-700 border-teal-200"
      : "bg-rose-50 text-rose-700 border-rose-200";

  const apiDotClass = isCheckingBackend
    ? "bg-amber-400"
    : isBackendOnline
      ? "bg-teal-500"
      : "bg-rose-500";

  return (
    <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/95 backdrop-blur-sm">
      <div className="flex items-center justify-between gap-4 px-4 py-3.5 sm:px-6 lg:px-8">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={onOpenMobileMenu}
            className="rounded-lg border border-slate-200 p-2 text-slate-600 hover:bg-slate-50 lg:hidden"
            aria-label="Open navigation menu"
          >
            <Menu className="h-5 w-5" />
          </button>
          <div>
            <h1 className="text-base font-semibold text-[#0F2942] sm:text-lg">
              {TAB_TITLES[activeTab] || "MediVoice AI"}
            </h1>
            <p className="hidden text-xs text-slate-500 sm:block">
              Real-time voice appointment scheduling powered by Pipecat, Gemini &amp; ElevenLabs
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          <div className="hidden items-center gap-1.5 rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-medium text-slate-600 md:flex">
            <ShieldCheck className="h-3.5 w-3.5 text-teal-600" />
            <span>{isVoiceReady ? "Voice Pipeline Ready" : "Voice Keys Pending"}</span>
          </div>

          <div
            className={`flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium ${apiBadgeClass}`}
          >
            <span className={`h-2 w-2 rounded-full ${apiDotClass}`} />
            <span>
              {isCheckingBackend
                ? "Checking API"
                : isBackendOnline
                  ? "API Online"
                  : "API Offline"}
            </span>
          </div>
        </div>
      </div>
    </header>
  );
}
