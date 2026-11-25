"use client";

import {
  CheckCircle2,
  AlertCircle,
  RefreshCw,
  Server,
  KeyRound,
  Database,
} from "lucide-react";

function ReadinessRow({ icon: Icon, label, configured, detail }) {
  return (
    <div className="flex items-center justify-between rounded-lg border border-slate-200/80 bg-slate-50/70 px-3.5 py-2.5">
      <div className="flex items-center gap-2.5">
        <Icon className="h-4 w-4 text-slate-500" />
        <div>
          <p className="text-sm font-medium text-[#0F2942]">{label}</p>
          {detail ? <p className="text-xs text-slate-500">{detail}</p> : null}
        </div>
      </div>

      {configured ? (
        <span className="inline-flex items-center gap-1 rounded-full bg-teal-50 px-2.5 py-0.5 text-xs font-medium text-teal-700">
          <CheckCircle2 className="h-3.5 w-3.5" />
          Configured
        </span>
      ) : (
        <span className="inline-flex items-center gap-1 rounded-full bg-slate-200/70 px-2.5 py-0.5 text-xs font-medium text-slate-600">
          Pending
        </span>
      )}
    </div>
  );
}

export default function BackendHealthCard({
  apiUrl,
  health,
  error,
  isChecking,
  onRefresh,
}) {
  const envKeys = health?.env_keys || {};

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-xs transition-shadow hover:shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-100 pb-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-teal-50 text-teal-700">
            <Server className="h-5 w-5" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-[#0F2942]">
              Backend Service Health
            </h2>
            <p className="text-xs text-slate-500">
              Live check against{" "}
              <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-700">
                {apiUrl}/health
              </code>
            </p>
          </div>
        </div>

        <button
          type="button"
          onClick={onRefresh}
          disabled={isChecking}
          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-[#0F2942] transition-colors hover:border-teal-300 hover:bg-teal-50/50 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${isChecking ? "animate-spin" : ""}`} />
          {isChecking ? "Checking..." : "Refresh"}
        </button>
      </div>

      <div className="mt-5">
        {error ? (
          <div className="rounded-xl border border-amber-200 bg-amber-50/70 p-4">
            <div className="flex items-start gap-3">
              <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
              <div className="space-y-1 text-sm">
                <p className="font-medium text-amber-900">
                  FastAPI backend is not reachable yet
                </p>
                <p className="text-xs text-amber-800/90">
                  {error}. Start the backend server on port 8000 and click Refresh
                  to verify live connectivity.
                </p>
              </div>
            </div>
          </div>
        ) : health ? (
          <div className="space-y-4">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="rounded-xl border border-teal-200/80 bg-teal-50/50 p-3.5">
                <p className="text-xs font-medium uppercase tracking-wider text-teal-700">
                  API Status
                </p>
                <p className="mt-1 text-lg font-semibold text-[#0F2942]">
                  {health.status === "ok" ? "Healthy" : health.status}
                </p>
              </div>
              <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-3.5">
                <p className="text-xs font-medium uppercase tracking-wider text-slate-500">
                  Python Runtime
                </p>
                <p className="mt-1 font-mono text-lg font-semibold text-[#0F2942]">
                  Python {health.python_version}
                </p>
              </div>
            </div>

            <div className="space-y-2">
              <p className="text-xs font-medium uppercase tracking-wider text-slate-400">
                Environment Readiness (Phase 2+ Prerequisites)
              </p>
              <ReadinessRow
                icon={Database}
                label="SQLite Database Path"
                detail="DATABASE_URL configuration"
                configured={Boolean(health.database_configured)}
              />
              <ReadinessRow
                icon={KeyRound}
                label="Google Gemini API Key"
                detail="GEMINI_API_KEY (LLM for Phase 2)"
                configured={Boolean(envKeys.gemini_api_key)}
              />
              <ReadinessRow
                icon={KeyRound}
                label="ElevenLabs API Key"
                detail="ELEVENLABS_API_KEY (STT & TTS for Phase 2)"
                configured={Boolean(envKeys.elevenlabs_api_key)}
              />
            </div>
          </div>
        ) : (
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">
            Checking backend connection...
          </div>
        )}
      </div>
    </section>
  );
}
