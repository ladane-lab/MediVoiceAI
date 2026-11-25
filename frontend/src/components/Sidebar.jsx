"use client";

import {
  Activity,
  CalendarDays,
  LayoutDashboard,
  PhoneCall,
  Stethoscope,
  X,
} from "lucide-react";

const NAV_ITEMS = [
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { id: "doctors", label: "Find Doctors", icon: Stethoscope },
  { id: "appointments", label: "My Appointments", icon: CalendarDays },
  { id: "voice", label: "Voice Assistant", icon: PhoneCall },
];

export default function Sidebar({
  activeTab,
  onSelectTab,
  voiceCallStatus,
  mobileOpen,
  onCloseMobile,
}) {
  const isCallLive =
    voiceCallStatus === "connected" ||
    voiceCallStatus === "connecting" ||
    voiceCallStatus === "reconnecting";

  const content = (
    <div className="flex h-full flex-col justify-between bg-[#0F2942] px-4 py-6 text-white">
      <div>
        <div className="flex items-center justify-between px-2">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-white/10 ring-1 ring-white/15">
              <Activity className="h-5 w-5 text-teal-300" strokeWidth={2.2} />
            </div>
            <div>
              <p className="text-base font-semibold tracking-tight text-white">
                MediVoice AI
              </p>
              <p className="text-[11px] text-slate-300">
                Clinical Voice Portal
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={onCloseMobile}
            className="rounded-lg p-1.5 text-slate-300 hover:bg-white/10 lg:hidden"
            aria-label="Close navigation menu"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <nav className="mt-8 space-y-1.5" aria-label="Primary navigation">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => {
                  onSelectTab(item.id);
                  onCloseMobile?.();
                }}
                className={`flex w-full items-center justify-between rounded-xl px-3.5 py-2.5 text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-teal-500/20 text-teal-200 ring-1 ring-teal-400/30"
                    : "text-slate-300 hover:bg-white/5 hover:text-white"
                }`}
              >
                <span className="flex items-center gap-3">
                  <Icon className="h-4 w-4" />
                  <span>{item.label}</span>
                </span>
                {item.id === "voice" && isCallLive ? (
                  <span className="h-2 w-2 rounded-full bg-teal-400" />
                ) : null}
              </button>
            );
          })}
        </nav>
      </div>

      <div className="rounded-xl border border-white/10 bg-white/5 p-3.5 text-xs text-slate-300">
        <p className="font-medium text-white">Phone-Based Demo Access</p>
        <p className="mt-1 leading-relaxed text-slate-300/90">
          No login required. Callers verify identity using their spoken phone
          number during voice calls or appointment lookup.
        </p>
      </div>
    </div>
  );

  return (
    <>
      {/* Desktop sidebar */}
      <aside className="hidden w-64 shrink-0 lg:block">{content}</aside>

      {/* Mobile slide-over sidebar */}
      {mobileOpen ? (
        <div className="fixed inset-0 z-40 flex lg:hidden">
          <div
            className="fixed inset-0 bg-slate-900/50 backdrop-blur-xs"
            onClick={onCloseMobile}
          />
          <aside className="relative z-50 w-72 max-w-[85vw]">{content}</aside>
        </div>
      ) : null}
    </>
  );
}
