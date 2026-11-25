"""Pipecat voice pipeline assembly using SmallWebRTC, ElevenLabs, Silero VAD, and Google Gemini."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import logging
from typing import Any
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    ErrorFrame,
    Frame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.elevenlabs.stt import ElevenLabsRealtimeSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.google.llm import GoogleLLMService
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

from app.config import Settings
from app.voice.prompts import build_system_prompt
from app.voice.tools import VoiceConversationState, build_voice_tools

logger = logging.getLogger(__name__)


class VoiceConfigurationError(Exception):
    """Raised when required Gemini or ElevenLabs credentials are missing."""

    def __init__(self, missing_vars: list[str]):
        self.missing_vars = missing_vars
        joined = ", ".join(missing_vars)
        super().__init__(
            f"Voice assistant is not configured. Missing environment variables: {joined}."
        )


def validate_voice_configuration(settings: Settings) -> None:
    """Verify all required AI and voice provider credentials are present."""
    missing = settings.missing_voice_env_vars()
    if missing:
        raise VoiceConfigurationError(missing)


def sanitize_pipeline_error(raw_error: str) -> str:
    """Map raw provider errors to safe, user-friendly messages without leaking secrets."""
    lower = (raw_error or "").lower()
    if "429" in lower or "resource_exhausted" in lower or "quota" in lower or "rate_limit" in lower:
        return (
            "The AI service rate or daily quota limit was reached. "
            "Wait a moment or switch GEMINI_MODEL in .env and try again."
        )
    if "402" in lower or "payment_required" in lower or "library voices" in lower:
        return (
            "ElevenLabs TTS rejected the configured voice on your current plan. "
            "Check ELEVENLABS_VOICE_ID in .env."
        )
    if "401" in lower or "403" in lower or "unauthorized" in lower or "api key" in lower or "auth" in lower:
        return "Voice service authentication failed. Verify your backend API keys in .env."
    if "503" in lower or "unavailable" in lower or "high demand" in lower:
        return "The Gemini model is temporarily overloaded (503). Please speak again in a few seconds."
    if "404" in lower or "not_found" in lower:
        return "Configured Gemini model was not found. Check GEMINI_MODEL in .env."
    return "The voice assistant encountered a temporary service error. Please try again."


class UserTurnTranscriptObserver(FrameProcessor):
    """
    Observes finalized ElevenLabs STT TranscriptionFrames and upstream ErrorFrames.

    Advances VoiceConversationState for caller confirmation checks, transitions the
    UI into 'thinking' once speech is recognized, and forwards any upstream provider
    errors (e.g. Gemini 429/503 or ElevenLabs TTS errors) to the browser.
    """

    def __init__(
        self,
        state: VoiceConversationState,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ):
        super().__init__()
        self._state = state
        self._on_event = on_event
        self._seq = 0

    def _emit(self, payload: dict[str, Any]) -> None:
        if self._on_event is not None:
            self._on_event(payload)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame) and frame.text.strip():
            cleaned = frame.text.strip()
            self._seq += 1
            turn_id = f"user-{self._seq}"
            logger.info(
                "Pipeline stage=stt_committed turn_id=%s chars=%d",
                turn_id,
                len(cleaned),
            )
            self._state.record_user_turn(cleaned, turn_id=turn_id)
            self._emit(
                {
                    "type": "transcript",
                    "id": turn_id,
                    "role": "user",
                    "text": cleaned,
                    "final": True,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
            self._emit({"type": "activity", "stage": "thinking", "speaker": "assistant", "speaking": False})
        elif isinstance(frame, ErrorFrame):
            friendly = sanitize_pipeline_error(str(getattr(frame, "error", "")))
            logger.error("Pipeline ErrorFrame caught (direction=%s): %s", direction.name, friendly)
            self._emit({"type": "error", "stage": "error", "message": friendly})

        await self.push_frame(frame, direction)


class AssistantEventsObserver(FrameProcessor):
    """
    Captures Gemini response text frames, user VAD speaking state, and any
    downstream ErrorFrames to emit live transcripts and Listening/Thinking state.
    """

    def __init__(self, on_event: Callable[[dict[str, Any]], None] | None = None):
        super().__init__()
        self._on_event = on_event
        self._turn_seq = 0
        self._current_turn_id: str | None = None
        self._buffer: str = ""

    def _emit(self, payload: dict[str, Any]) -> None:
        if self._on_event is not None:
            self._on_event(payload)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, UserStartedSpeakingFrame):
            logger.info("Pipeline stage=vad_user_started")
            self._emit({"type": "activity", "stage": "listening", "speaker": "user", "speaking": True})
        elif isinstance(frame, UserStoppedSpeakingFrame):
            logger.info("Pipeline stage=vad_user_stopped")
            self._emit({"type": "activity", "stage": "thinking", "speaker": "user", "speaking": False})
        elif isinstance(frame, LLMFullResponseStartFrame):
            self._turn_seq += 1
            self._current_turn_id = f"assistant-{self._turn_seq}"
            self._buffer = ""
            logger.info("Pipeline stage=llm_response_start turn_id=%s", self._current_turn_id)
            self._emit({"type": "activity", "stage": "thinking", "speaker": "assistant", "speaking": False})
        elif isinstance(frame, LLMTextFrame):
            if self._current_turn_id is None:
                self._turn_seq += 1
                self._current_turn_id = f"assistant-{self._turn_seq}"
                self._buffer = ""
            self._buffer += frame.text
            if self._buffer.strip():
                self._emit(
                    {
                        "type": "transcript",
                        "id": self._current_turn_id,
                        "role": "assistant",
                        "text": self._buffer.strip(),
                        "final": False,
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                )
        elif isinstance(frame, LLMFullResponseEndFrame):
            if self._current_turn_id and self._buffer.strip():
                logger.info(
                    "Pipeline stage=llm_response_end turn_id=%s chars=%d",
                    self._current_turn_id,
                    len(self._buffer.strip()),
                )
                self._emit(
                    {
                        "type": "transcript",
                        "id": self._current_turn_id,
                        "role": "assistant",
                        "text": self._buffer.strip(),
                        "final": True,
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                )
            self._current_turn_id = None
            self._buffer = ""
        elif isinstance(frame, ErrorFrame):
            friendly = sanitize_pipeline_error(str(getattr(frame, "error", "")))
            logger.error("Pipeline downstream ErrorFrame: %s", friendly)
            self._emit({"type": "error", "stage": "error", "message": friendly})

        await self.push_frame(frame, direction)


class BotSpeakingObserver(FrameProcessor):
    """Tracks actual WebRTC audio output speaking state for the assistant."""

    def __init__(self, on_event: Callable[[dict[str, Any]], None] | None = None):
        super().__init__()
        self._on_event = on_event

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if self._on_event is not None:
            if isinstance(frame, BotStartedSpeakingFrame):
                logger.info("Pipeline stage=tts_speaking_started")
                self._on_event(
                    {"type": "activity", "stage": "speaking", "speaker": "assistant", "speaking": True}
                )
            elif isinstance(frame, BotStoppedSpeakingFrame):
                logger.info("Pipeline stage=tts_speaking_stopped")
                self._on_event(
                    {"type": "activity", "stage": "listening", "speaker": "assistant", "speaking": False}
                )
        await self.push_frame(frame, direction)


@dataclass
class VoicePipelineBundle:
    """Container holding the Pipecat pipeline, task, transport, and session state."""

    transport: SmallWebRTCTransport
    pipeline: Pipeline
    task: PipelineTask
    context: LLMContext
    state: VoiceConversationState


def build_voice_pipeline(
    webrtc_connection: SmallWebRTCConnection,
    settings: Settings,
    state: VoiceConversationState | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> VoicePipelineBundle:
    """
    Construct a real-time Pipecat audio pipeline for a browser WebRTC connection.

    Pipeline flow:
    Browser Audio -> SmallWebRTC Input -> ElevenLabs Realtime STT -> UserTranscriptObserver
    -> User Aggregator (Silero VAD) -> Google Gemini LLM (Function Calling)
    -> AssistantEventsObserver -> ElevenLabs TTS -> SmallWebRTC Output -> BotSpeakingObserver
    -> Assistant Aggregator
    """
    validate_voice_configuration(settings)
    session_state = state or VoiceConversationState()
    system_prompt = build_system_prompt()
    tools = build_voice_tools(session_state, on_event=on_event)

    transport = SmallWebRTCTransport(
        webrtc_connection=webrtc_connection,
        params=TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        ),
    )

    stt = ElevenLabsRealtimeSTTService(
        api_key=settings.elevenlabs_api_key,
        settings=ElevenLabsRealtimeSTTService.Settings(
            model="scribe_v2_realtime",
        ),
    )

    tts = ElevenLabsTTSService(
        api_key=settings.elevenlabs_api_key,
        settings=ElevenLabsTTSService.Settings(
            voice=settings.elevenlabs_voice_id,
            model="eleven_flash_v2_5",
        ),
    )

    llm = GoogleLLMService(
        api_key=settings.gemini_api_key,
        settings=GoogleLLMService.Settings(
            model=settings.gemini_model,
            system_instruction=system_prompt,
        ),
        retry_on_timeout=True,
    )

    context = LLMContext(
        messages=[
            {
                "role": "user",
                "content": (
                    "Greet the caller briefly as MediVoice AI and ask how you can help "
                    "with their doctor appointment today."
                ),
            }
        ],
        tools=tools,
    )

    context_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(
                params=VADParams(stop_secs=0.6),
            ),
            user_turn_stop_timeout=1.5,
        ),
    )

    transcript_observer = UserTurnTranscriptObserver(session_state, on_event=on_event)
    assistant_observer = AssistantEventsObserver(on_event=on_event)
    bot_speaking_observer = BotSpeakingObserver(on_event=on_event)

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            transcript_observer,
            context_aggregator.user(),
            llm,
            assistant_observer,
            tts,
            transport.output(),
            bot_speaking_observer,
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            enable_metrics=False,
        ),
    )

    return VoicePipelineBundle(
        transport=transport,
        pipeline=pipeline,
        task=task,
        context=context,
        state=session_state,
    )
