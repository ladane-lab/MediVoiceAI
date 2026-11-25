"""WebRTC voice session lifecycle management for Pipecat connections."""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
import logging
import uuid
from aiortc import RTCIceServer
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.runner import PipelineRunner
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.request_handler import (
    IceCandidate,
    SmallWebRTCPatchRequest,
    SmallWebRTCRequest,
    SmallWebRTCRequestHandler,
)

from app.config import Settings, get_settings
from app.voice.agent import (
    VoiceConfigurationError,
    build_voice_pipeline,
    validate_voice_configuration,
)
from app.voice.tools import VoiceConversationState

logger = logging.getLogger(__name__)


@dataclass
class VoiceSessionRecord:
    """Tracks an active or completed browser-to-Pipecat WebRTC session."""

    session_id: str
    status: str = "pending"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    pc_id: str | None = None
    state: VoiceConversationState = field(default_factory=VoiceConversationState)
    connection: SmallWebRTCConnection | None = None
    runner_task: asyncio.Task | None = None
    pipeline_task: object | None = None
    error: str | None = None


class VoiceSessionManager:
    """Manages WebRTC signaling, Pipecat pipeline tasks, and clean teardown."""

    def __init__(self, settings: Settings | None = None):
        self._settings = settings or get_settings()
        ice_servers = [RTCIceServer(urls=url) for url in self._settings.ice_servers_list]
        self._request_handler = SmallWebRTCRequestHandler(ice_servers=ice_servers)
        self._sessions: dict[str, VoiceSessionRecord] = {}
        self._pc_to_session: dict[str, str] = {}

    def get_status(self) -> dict:
        """Return non-secret readiness and active session counts."""
        missing = self._settings.missing_voice_env_vars()
        active_count = sum(
            1 for record in self._sessions.values() if record.status in ("pending", "connected")
        )
        return {
            "ready": len(missing) == 0,
            "transport": "smallwebrtc",
            "llm_provider": "google_gemini",
            "llm_model": self._settings.gemini_model,
            "stt_provider": "elevenlabs",
            "tts_provider": "elevenlabs",
            "missing_env_vars": missing,
            "active_sessions": active_count,
        }

    def create_session(self) -> dict:
        """Validate voice credentials and create a tracked session ID."""
        validate_voice_configuration(self._settings)
        session_id = uuid.uuid4().hex
        self._sessions[session_id] = VoiceSessionRecord(session_id=session_id)
        return {
            "session_id": session_id,
            "status": "pending",
            "transport": "smallwebrtc",
            "offer_url": "/api/voice/offer",
            "ice_servers": self._settings.ice_servers_list,
        }

    def get_session_summary(self, session_id: str) -> dict | None:
        """Return sanitized session metadata without exposing keys or raw phone numbers."""
        record = self._sessions.get(session_id)
        if not record:
            return None
        return {
            "session_id": record.session_id,
            "pc_id": record.pc_id,
            "status": record.status,
            "created_at": record.created_at,
            "phone_confirmed": record.state.confirmed_phone_number is not None,
            "pending_phone_confirmation": record.state.pending_phone_number is not None
            and record.state.confirmed_phone_number is None,
            "pending_cancellation_id": record.state.pending_cancellation_id,
            "error": record.error,
        }

    async def handle_offer(
        self,
        sdp: str,
        sdp_type: str = "offer",
        pc_id: str | None = None,
        restart_pc: bool | None = None,
        session_id: str | None = None,
    ) -> dict:
        """Process a browser WebRTC SDP offer and start the Pipecat voice pipeline."""
        validate_voice_configuration(self._settings)

        target_session_id = session_id or (self._pc_to_session.get(pc_id) if pc_id else None)
        if not target_session_id or target_session_id not in self._sessions:
            target_session_id = uuid.uuid4().hex
            self._sessions[target_session_id] = VoiceSessionRecord(session_id=target_session_id)

        record = self._sessions[target_session_id]
        request = SmallWebRTCRequest(
            sdp=sdp,
            type=sdp_type,
            pc_id=pc_id,
            restart_pc=restart_pc,
        )

        async def on_webrtc_connection(webrtc_connection: SmallWebRTCConnection):
            bundle = build_voice_pipeline(
                webrtc_connection=webrtc_connection,
                settings=self._settings,
                state=record.state,
            )
            record.connection = webrtc_connection
            record.pc_id = webrtc_connection.pc_id
            record.pipeline_task = bundle.task
            self._pc_to_session[webrtc_connection.pc_id] = record.session_id

            @bundle.transport.event_handler("on_client_connected")
            async def on_client_connected(_transport, _client):
                record.status = "connected"
                await bundle.task.queue_frames([LLMRunFrame()])

            @bundle.transport.event_handler("on_client_disconnected")
            async def on_client_disconnected(_transport, _client):
                record.status = "disconnected"
                await bundle.task.cancel()

            runner = PipelineRunner(handle_sigint=False)

            async def _run_pipeline():
                try:
                    await runner.run(bundle.task)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.exception("Voice pipeline error in session %s: %s", record.session_id, exc)
                    record.status = "error"
                    record.error = "Voice pipeline encountered an unexpected error."
                finally:
                    if record.status == "connected":
                        record.status = "ended"

            record.runner_task = asyncio.create_task(_run_pipeline())

        answer = await self._request_handler.handle_web_request(request, on_webrtc_connection)
        if answer is None:
            raise RuntimeError("WebRTC negotiation failed to produce an SDP answer.")

        record.pc_id = answer["pc_id"]
        self._pc_to_session[answer["pc_id"]] = record.session_id
        return {
            "sdp": answer["sdp"],
            "type": answer["type"],
            "pc_id": answer["pc_id"],
            "session_id": record.session_id,
        }

    async def handle_ice_patch(self, pc_id: str, candidates: list[dict]) -> None:
        """Apply trickle ICE candidates to an existing SmallWebRTC peer connection."""
        validate_voice_configuration(self._settings)
        ice_objects = [
            IceCandidate(
                candidate=item["candidate"],
                sdp_mid=item.get("sdp_mid"),
                sdp_mline_index=item.get("sdp_mline_index"),
            )
            for item in candidates
        ]
        patch = SmallWebRTCPatchRequest(pc_id=pc_id, candidates=ice_objects)
        await self._request_handler.handle_patch_request(patch)

    async def end_session(self, session_id: str) -> dict | None:
        """Cleanly cancel the Pipecat pipeline and close the WebRTC connection."""
        record = self._sessions.get(session_id)
        if not record:
            return None

        if record.pipeline_task is not None:
            try:
                await record.pipeline_task.cancel()
            except Exception:
                logger.warning("Error cancelling pipeline task for session %s", session_id)

        if record.connection is not None:
            try:
                await record.connection.disconnect()
            except Exception:
                logger.warning("Error disconnecting WebRTC peer for session %s", session_id)

        if record.runner_task is not None and not record.runner_task.done():
            record.runner_task.cancel()
            try:
                await record.runner_task
            except (asyncio.CancelledError, Exception):
                pass

        record.status = "ended"
        return {
            "success": True,
            "session_id": session_id,
            "status": "ended",
            "message": "Voice session ended.",
        }

    async def shutdown_all(self) -> None:
        """Shut down all active voice sessions on backend shutdown."""
        for session_id in list(self._sessions.keys()):
            await self.end_session(session_id)
        try:
            await self._request_handler.close()
        except Exception:
            pass
