"use client";

import { useEffect, useRef } from "react";
import {
  AlertCircle,
  Bot,
  Mic,
  MicOff,
  Phone,
  PhoneOff,
  Radio,
  User,
  Volume2,
} from "lucide-react";

function formatDuration(totalSeconds) {
  const mins = Math.floor(totalSeconds / 60);
  const secs = totalSeconds % 60;
  return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

const STATUS_META = {
  idle: { label: "Ready to Call", badge: "bg-slate-100 text-slate-700 border-slate-200" },
  connecting: { label: "Connecting", badge: "bg-amber-50 text-amber-700 border-amber-200" },
  connected: { label: "Connected", badge: "bg-teal-50 text-teal-700 border-teal-200" },
  reconnecting: { label: "Reconnecting", badge: "bg-amber-50 text-amber-700 border-amber-200" },
  disconnected: { label: "Disconnected", badge: "bg-slate-100 text-slate-700 border-slate-200" },
  ended: { label: "Call Ended", badge: "bg-slate-100 text-slate-700 border-slate-200" },
  error: { label: "Error", badge: "bg-rose-50 text-rose-700 border-rose-200" },
};

export default function VoiceAssistantCard({
  voiceCall,
  voiceStatus,
  expanded = false,
}) {
  const {
    status,
    isMuted,
    durationSeconds,
    transcript,
    userSpeaking,
    assistantSpeaking,
    micLevel,
    errorMessage,
    startCall,
    endCall,
    toggleMute,
  } = voiceCall;

  const transcriptEndRef = useRef(null);

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [transcript]);

  const isActive = status === "connecting" || status === "connected" || status === "reconnecting";
  const statusInfo = STATUS_META[status] || STATUS_META.idle;
  const isReady = Boolean(voiceStatus?.ready);

  const activityLabel =
    status !== "connected"
      ? statusInfo.label
      : assistantSpeaking
        ? "MediVoice AI is speaking..."
        : isMuted
          ? "Microphone muted"
          : userSpeaking
            ? "Listening to your voice..."
            : "Listening — speak whenever ready";

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-xs">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-100 pb-4">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-[#0F2942] text-teal-300">
            <Radio className="h-5 w-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-semibold text-[#0F2942]">
                MediVoice AI
              </h2>
              <span
                className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${statusInfo.badge}`}
              >
                {statusInfo.label}
              </span>
            </div>
            <p className="text-xs text-slate-500">
              WebRTC voice assistant for checking slots, booking &amp; cancelling appointments
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {status === "connected" || status === "ended" ? (
            <span className="rounded-lg bg-slate-100 px-2.5 py-1 font-mono text-xs font-medium text-slate-700">
              {formatDuration(durationSeconds)}
            </span>
          ) : null}

          {!isActive ? (
            <button
              type="button"
              onClick={startCall}
              disabled={!isReady}
              className="inline-flex items-center gap-2 rounded-xl bg-teal-600 px-4 py-2.5 text-sm font-medium text-white shadow-xs transition-colors hover:bg-teal-700 disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              <Phone className="h-4 w-4" />
              {status === "ended" ? "Start New Call" : "Start Call"}
            </button>
          ) : (
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={toggleMute}
                disabled={status !== "connected"}
                className={`inline-flex items-center gap-1.5 rounded-xl border px-3.5 py-2.5 text-sm font-medium transition-colors disabled:opacity-50 ${
                  isMuted
                    ? "border-amber-300 bg-amber-50 text-amber-800 hover:bg-amber-100"
                    : "border-slate-200 bg-white text-[#0F2942] hover:bg-slate-50"
                }`}
              >
                {isMuted ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
                {isMuted ? "Unmute" : "Mute"}
              </button>

              <button
                type="button"
                onClick={endCall}
                className="inline-flex items-center gap-1.5 rounded-xl bg-rose-600 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-rose-700"
              >
                <PhoneOff className="h-4 w-4" />
                End Call
              </button>
            </div>
          )}
        </div>
      </div>

      {!isReady && voiceStatus ? (
        <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50/70 p-3.5 text-xs text-amber-900">
          Backend voice credentials are missing (
          {(voiceStatus.missing_env_vars || []).join(", ")}). Configure them in{" "}
          <code className="rounded bg-amber-100 px-1 py-0.5 font-mono">.env</code> to enable live WebRTC calls.
        </div>
      ) : null}

      {errorMessage ? (
        <div className="mt-4 flex items-start gap-2.5 rounded-xl border border-rose-200 bg-rose-50 p-3.5 text-xs text-rose-800">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-rose-600" />
          <p>{errorMessage}</p>
        </div>
      ) : null}

      {/* Real speaking / listening activity bar */}
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200/80 bg-slate-50/80 px-4 py-3">
        <div className="flex items-center gap-2.5">
          {assistantSpeaking ? (
            <Volume2 className="h-4 w-4 text-teal-600" />
          ) : isMuted ? (
            <MicOff className="h-4 w-4 text-amber-600" />
          ) : (
            <Mic
              className={`h-4 w-4 ${
                userSpeaking ? "text-teal-600" : "text-slate-400"
              }`}
            />
          )}
          <span className="text-xs font-medium text-slate-700">{activityLabel}</span>
        </div>

        {/* Truthful real-time mic input level meter only when Web Audio AnalyserNode data is active */}
        {status === "connected" && micLevel !== null ? (
          <div className="flex items-center gap-2" aria-label="Live microphone input level">
            <span className="text-[11px] text-slate-500">Mic</span>
            <div className="h-2 w-24 overflow-hidden rounded-full bg-slate-200">
              <div
                className="h-full rounded-full bg-teal-500 transition-[width] duration-75"
                style={{ width: `${Math.round(micLevel * 100)}%` }}
              />
            </div>
          </div>
        ) : null}
      </div>

      {/* Live Transcript */}
      <div
        className={`mt-4 overflow-y-auto rounded-xl border border-slate-200/80 bg-slate-50/50 p-4 ${
          expanded ? "h-96" : "h-64"
        }`}
      >
        {transcript.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <p className="text-sm font-medium text-slate-600">
              {status === "connected"
                ? "Connected — waiting for the conversation to begin..."
                : status === "ended"
                  ? "Call ended with no recorded transcript."
                  : "Live transcript will appear here once you start a call."}
            </p>
            <p className="mt-1 max-w-md text-xs text-slate-500">
              When booking or cancelling, MediVoice AI will repeat your phone number
              digit by digit and ask you to confirm clearly.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {transcript.map((item) => {
              const isUser = item.role === "user";
              return (
                <div
                  key={item.id}
                  className={`flex items-start gap-2.5 ${
                    isUser ? "justify-end" : "justify-start"
                  }`}
                >
                  {!isUser ? (
                    <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-[#0F2942] text-teal-300">
                      <Bot className="h-3.5 w-3.5" />
                    </div>
                  ) : null}

                  <div
                    className={`max-w-[82%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed ${
                      isUser
                        ? "bg-teal-600 text-white"
                        : "border border-slate-200 bg-white text-[#0F2942]"
                    }`}
                  >
                    <p className="mb-0.5 text-[10px] font-semibold uppercase tracking-wider opacity-75">
                      {isUser ? "Caller" : "MediVoice AI"}
                    </p>
                    <p>{item.text}</p>
                  </div>

                  {isUser ? (
                    <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-teal-100 text-teal-800">
                      <User className="h-3.5 w-3.5" />
                    </div>
                  ) : null}
                </div>
              );
            })}
            <div ref={transcriptEndRef} />
          </div>
        )}
      </div>
    </section>
  );
}
