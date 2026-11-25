"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  createVoiceSession,
  endVoiceSession,
  fetchVoiceSessionSummary,
  sendVoiceIcePatch,
  sendVoiceOffer,
} from "@/lib/api";

function mapMicrophoneError(err) {
  if (!err || typeof err !== "object") {
    return "Unable to access your microphone.";
  }
  if (err.name === "NotAllowedError" || err.name === "PermissionDeniedError") {
    return "Microphone permission was denied. Please allow microphone access in your browser and try again.";
  }
  if (err.name === "NotFoundError" || err.name === "DevicesNotFoundError") {
    return "No microphone device was found. Please connect a microphone and try again.";
  }
  if (err.name === "NotReadableError") {
    return "Your microphone is busy in another application. Close other audio apps and retry.";
  }
  return err.message || "Unable to start microphone audio.";
}

function waitForIceGathering(pc, timeoutMs = 1200) {
  if (pc.iceGatheringState === "complete") {
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      pc.removeEventListener("icegatheringstatechange", onChange);
      resolve();
    }, timeoutMs);

    function onChange() {
      if (pc.iceGatheringState === "complete") {
        clearTimeout(timer);
        pc.removeEventListener("icegatheringstatechange", onChange);
        resolve();
      }
    }

    pc.addEventListener("icegatheringstatechange", onChange);
  });
}

/**
 * Reusable WebRTC voice hook connecting the browser directly to Pipecat's
 * SmallWebRTC signaling endpoints and real-time audio/data channels.
 */
export default function useVoiceCall({ remoteAudioRef, onAppointmentUpdated } = {}) {
  const [status, setStatus] = useState("idle"); // idle | connecting | connected | reconnecting | disconnected | ended | error
  const [isMuted, setIsMuted] = useState(false);
  const [durationSeconds, setDurationSeconds] = useState(0);
  const [transcript, setTranscript] = useState([]);
  const [userSpeaking, setUserSpeaking] = useState(false);
  const [assistantSpeaking, setAssistantSpeaking] = useState(false);
  const [micLevel, setMicLevel] = useState(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [sessionId, setSessionId] = useState(null);

  const pcRef = useRef(null);
  const dataChannelRef = useRef(null);
  const localStreamRef = useRef(null);
  const sessionIdRef = useRef(null);
  const pcIdRef = useRef(null);
  const pendingIceRef = useRef([]);
  const startingRef = useRef(false);
  const endingRef = useRef(false);
  const isMutedRef = useRef(false);
  const audioContextRef = useRef(null);
  const meterFrameRef = useRef(null);
  const onAppointmentUpdatedRef = useRef(onAppointmentUpdated);

  useEffect(() => {
    onAppointmentUpdatedRef.current = onAppointmentUpdated;
  }, [onAppointmentUpdated]);

  const stopAudioMeter = useCallback(() => {
    if (meterFrameRef.current) {
      cancelAnimationFrame(meterFrameRef.current);
      meterFrameRef.current = null;
    }
    if (audioContextRef.current) {
      audioContextRef.current.close().catch(() => {});
      audioContextRef.current = null;
    }
    setMicLevel(null);
  }, []);

  const startAudioMeter = useCallback(
    (stream) => {
      stopAudioMeter();
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;

      try {
        const audioCtx = new AudioCtx();
        const source = audioCtx.createMediaStreamSource(stream);
        const analyser = audioCtx.createAnalyser();
        analyser.fftSize = 256;
        source.connect(analyser);

        const buffer = new Uint8Array(analyser.fftSize);
        audioContextRef.current = audioCtx;

        const updateMeter = () => {
          if (!audioContextRef.current) return;
          if (isMutedRef.current) {
            setMicLevel(0);
          } else {
            analyser.getByteTimeDomainData(buffer);
            let sumSquares = 0;
            for (let i = 0; i < buffer.length; i += 1) {
              const normalized = (buffer[i] - 128) / 128;
              sumSquares += normalized * normalized;
            }
            const rms = Math.sqrt(sumSquares / buffer.length);
            setMicLevel(Math.min(1, rms * 3.2));
          }
          meterFrameRef.current = requestAnimationFrame(updateMeter);
        };

        meterFrameRef.current = requestAnimationFrame(updateMeter);
      } catch {
        setMicLevel(null);
      }
    },
    [stopAudioMeter],
  );

  const upsertTranscriptEntry = useCallback((entry) => {
    if (!entry?.id || !entry?.text) return;
    setTranscript((prev) => {
      const idx = prev.findIndex((item) => item.id === entry.id);
      if (idx === -1) {
        return [...prev, entry];
      }
      const next = [...prev];
      next[idx] = entry;
      return next;
    });
  }, []);

  const handlePipelineEvent = useCallback(
    (payload) => {
      if (!payload || typeof payload !== "object") return;

      if (payload.type === "transcript") {
        upsertTranscriptEntry({
          id: payload.id,
          role: payload.role,
          text: payload.text,
          final: Boolean(payload.final),
          timestamp: payload.timestamp || null,
        });
      } else if (payload.type === "activity") {
        if (payload.speaker === "user") {
          setUserSpeaking(Boolean(payload.speaking));
        } else if (payload.speaker === "assistant") {
          setAssistantSpeaking(Boolean(payload.speaking));
        }
      } else if (payload.type === "appointment_updated") {
        onAppointmentUpdatedRef.current?.(payload);
      } else if (payload.type === "error" && payload.message) {
        setErrorMessage(payload.message);
      }
    },
    [upsertTranscriptEntry],
  );

  const cleanupPeerResources = useCallback(() => {
    stopAudioMeter();

    if (dataChannelRef.current) {
      try {
        dataChannelRef.current.close();
      } catch {
        // Ignore close errors
      }
      dataChannelRef.current = null;
    }

    if (pcRef.current) {
      try {
        pcRef.current.ontrack = null;
        pcRef.current.onicecandidate = null;
        pcRef.current.oniceconnectionstatechange = null;
        pcRef.current.onconnectionstatechange = null;
        pcRef.current.close();
      } catch {
        // Ignore close errors
      }
      pcRef.current = null;
    }

    if (localStreamRef.current) {
      localStreamRef.current.getTracks().forEach((track) => track.stop());
      localStreamRef.current = null;
    }

    if (remoteAudioRef?.current) {
      remoteAudioRef.current.srcObject = null;
    }

    pendingIceRef.current = [];
    pcIdRef.current = null;
    setUserSpeaking(false);
    setAssistantSpeaking(false);
  }, [remoteAudioRef, stopAudioMeter]);

  const endCall = useCallback(async () => {
    if (endingRef.current) return;
    endingRef.current = true;

    const activeSessionId = sessionIdRef.current;
    sessionIdRef.current = null;

    cleanupPeerResources();
    setIsMuted(false);
    isMutedRef.current = false;
    setStatus((prev) => (prev === "idle" ? "idle" : "ended"));

    if (activeSessionId) {
      try {
        await endVoiceSession(activeSessionId);
      } catch {
        // Session may already be closed
      }
    }

    endingRef.current = false;
  }, [cleanupPeerResources]);

  const startCall = useCallback(async () => {
    if (
      startingRef.current ||
      status === "connecting" ||
      status === "connected" ||
      status === "reconnecting"
    ) {
      return;
    }

    startingRef.current = true;
    setErrorMessage("");
    setTranscript([]);
    setDurationSeconds(0);
    setIsMuted(false);
    isMutedRef.current = false;
    setStatus("connecting");

    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error(
          "Your browser does not support WebRTC microphone access. Use Chrome, Edge, or Firefox over localhost or HTTPS.",
        );
      }

      const localStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
        video: false,
      });
      localStreamRef.current = localStream;
      startAudioMeter(localStream);

      const sessionData = await createVoiceSession();
      sessionIdRef.current = sessionData.session_id;
      setSessionId(sessionData.session_id);

      const iceServers = (sessionData.ice_servers || []).map((urls) => ({ urls }));
      const pc = new RTCPeerConnection({ iceServers });
      pcRef.current = pc;

      const dataChannel = pc.createDataChannel("medivoice");
      dataChannelRef.current = dataChannel;
      dataChannel.onmessage = (event) => {
        try {
          const parsed = JSON.parse(event.data);
          handlePipelineEvent(parsed);
        } catch {
          // Ignore non-JSON messages
        }
      };

      localStream.getTracks().forEach((track) => {
        pc.addTrack(track, localStream);
      });

      pc.ontrack = (event) => {
        const audioEl = remoteAudioRef?.current;
        if (!audioEl) return;
        const [stream] = event.streams;
        audioEl.srcObject = stream || new MediaStream([event.track]);
        audioEl.play().catch(() => {});
      };

      pc.onicecandidate = (event) => {
        const candidatePayload = {
          candidate: event.candidate ? event.candidate.candidate : "",
          sdp_mid: event.candidate?.sdpMid ?? "0",
          sdp_mline_index: event.candidate?.sdpMLineIndex ?? 0,
        };

        if (pcIdRef.current) {
          sendVoiceIcePatch({
            pc_id: pcIdRef.current,
            candidates: [candidatePayload],
          }).catch(() => {});
        } else {
          pendingIceRef.current.push(candidatePayload);
        }
      };

      pc.oniceconnectionstatechange = () => {
        const iceState = pc.iceConnectionState;
        if (iceState === "connected" || iceState === "completed") {
          setStatus("connected");
        } else if (iceState === "disconnected") {
          setStatus("reconnecting");
        } else if (iceState === "failed") {
          setErrorMessage("WebRTC audio connection failed. Please end the call and try again.");
          setStatus("error");
          cleanupPeerResources();
        } else if (iceState === "closed") {
          setStatus((prev) => (prev === "ended" || prev === "error" ? prev : "disconnected"));
        }
      };

      pc.onconnectionstatechange = () => {
        if (pc.connectionState === "connected") {
          setStatus("connected");
        } else if (pc.connectionState === "failed") {
          setErrorMessage("Peer connection failed. Check your network or backend server.");
          setStatus("error");
          cleanupPeerResources();
        }
      };

      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      await waitForIceGathering(pc, 1200);

      const localDesc = pc.localDescription;
      const answer = await sendVoiceOffer({
        sdp: localDesc.sdp,
        type: localDesc.type,
        session_id: sessionData.session_id,
      });

      pcIdRef.current = answer.pc_id;
      sessionIdRef.current = answer.session_id;
      setSessionId(answer.session_id);

      await pc.setRemoteDescription(
        new RTCSessionDescription({
          sdp: answer.sdp,
          type: answer.type,
        }),
      );

      if (pendingIceRef.current.length > 0) {
        const queued = [...pendingIceRef.current];
        pendingIceRef.current = [];
        sendVoiceIcePatch({
          pc_id: answer.pc_id,
          candidates: queued,
        }).catch(() => {});
      }
    } catch (err) {
      const msg = err?.name ? mapMicrophoneError(err) : err?.message || "Unable to connect call.";
      setErrorMessage(msg);
      setStatus("error");

      const failedSessionId = sessionIdRef.current;
      sessionIdRef.current = null;
      cleanupPeerResources();
      if (failedSessionId) {
        endVoiceSession(failedSessionId).catch(() => {});
      }
    } finally {
      startingRef.current = false;
    }
  }, [cleanupPeerResources, handlePipelineEvent, remoteAudioRef, startAudioMeter, status]);

  const toggleMute = useCallback(() => {
    if (!localStreamRef.current) return;
    const nextMuted = !isMutedRef.current;
    localStreamRef.current.getAudioTracks().forEach((track) => {
      track.enabled = !nextMuted;
    });
    isMutedRef.current = nextMuted;
    setIsMuted(nextMuted);
    if (nextMuted) {
      setUserSpeaking(false);
    }
  }, []);

  // Call duration timer while connected
  useEffect(() => {
    if (status !== "connected") return undefined;
    const timer = setInterval(() => {
      setDurationSeconds((prev) => prev + 1);
    }, 1000);
    return () => clearInterval(timer);
  }, [status]);

  // Lightweight fallback transcript sync while active (covers environments where DataChannel opens slowly)
  useEffect(() => {
    if (!sessionId || (status !== "connected" && status !== "reconnecting")) {
      return undefined;
    }
    const interval = setInterval(async () => {
      if (dataChannelRef.current?.readyState === "open") {
        return;
      }
      try {
        const summary = await fetchVoiceSessionSummary(sessionId);
        if (Array.isArray(summary?.transcript)) {
          summary.transcript.forEach(upsertTranscriptEntry);
        }
      } catch {
        // Ignore transient polling failures
      }
    }, 2500);

    return () => clearInterval(interval);
  }, [sessionId, status, upsertTranscriptEntry]);

  // Clean up microphone, peer connection, and backend session on page exit or unmount
  useEffect(() => {
    const handleUnload = () => {
      const activeId = sessionIdRef.current;
      if (activeId) {
        endVoiceSession(activeId, true);
      }
      cleanupPeerResources();
    };

    window.addEventListener("beforeunload", handleUnload);
    return () => {
      window.removeEventListener("beforeunload", handleUnload);
      handleUnload();
    };
  }, [cleanupPeerResources]);

  return {
    status,
    isMuted,
    durationSeconds,
    transcript,
    userSpeaking,
    assistantSpeaking,
    micLevel,
    errorMessage,
    sessionId,
    startCall,
    endCall,
    toggleMute,
  };
}
