import { CheckCircle2, Clock, Mic, CalendarClock, Layers } from "lucide-react";

const PHASES = [
  {
    id: "Phase 1",
    title: "Project Foundation & Architecture",
    description:
      "Separate Next.js (JSX + Tailwind) frontend and FastAPI Python backend, environment configuration, and live health verification.",
    status: "current",
    icon: Layers,
  },
  {
    id: "Phase 2",
    title: "SQLite Appointment & Doctor Schema",
    description:
      "Doctors, availability slots, and patient appointment persistence with clean REST endpoints.",
    status: "planned",
    icon: CalendarClock,
  },
  {
    id: "Phase 3",
    title: "Pipecat + WebRTC Voice Pipeline",
    description:
      "Real-time browser audio via WebRTC, ElevenLabs STT/TTS, and Google Gemini tool-calling for voice booking.",
    status: "planned",
    icon: Mic,
  },
];

export default function PhaseRoadmap() {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-xs transition-shadow hover:shadow-sm">
      <div className="border-b border-slate-100 pb-4">
        <h2 className="text-base font-semibold text-[#0F2942]">
          Implementation Roadmap
        </h2>
        <p className="text-xs text-slate-500">
          Incremental build plan — only Phase 1 foundation is active right now.
        </p>
      </div>

      <div className="mt-5 space-y-3">
        {PHASES.map((phase) => {
          const Icon = phase.icon;
          const isCurrent = phase.status === "current";

          return (
            <div
              key={phase.id}
              className={`rounded-xl border p-4 transition-colors ${
                isCurrent
                  ? "border-teal-200 bg-teal-50/40"
                  : "border-slate-200/80 bg-slate-50/50"
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-start gap-3">
                  <div
                    className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${
                      isCurrent
                        ? "bg-[#0F2942] text-teal-400"
                        : "bg-slate-200/70 text-slate-500"
                    }`}
                  >
                    <Icon className="h-4 w-4" />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                        {phase.id}
                      </span>
                    </div>
                    <h3 className="text-sm font-semibold text-[#0F2942]">
                      {phase.title}
                    </h3>
                    <p className="mt-1 text-xs leading-relaxed text-slate-600">
                      {phase.description}
                    </p>
                  </div>
                </div>

                {isCurrent ? (
                  <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-teal-100/80 px-2.5 py-0.5 text-xs font-medium text-teal-800">
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    Active
                  </span>
                ) : (
                  <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-slate-200/70 px-2.5 py-0.5 text-xs font-medium text-slate-600">
                    <Clock className="h-3.5 w-3.5" />
                    Planned
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
