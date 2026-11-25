"""Pipecat voice pipeline assembly using SmallWebRTC, ElevenLabs, Silero VAD, and Google Gemini."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
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


class UserTurnTranscriptObserver(FrameProcessor):
    """
    Observes finalized ElevenLabs STT TranscriptionFrames.

    Advances VoiceConversationState for caller confirmation checks and emits
    caller transcript events to the browser over WebRTC DataChannel.
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

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, TranscriptionFrame) and frame.text.strip():
            cleaned = frame.text.strip()
            self._state.record_user_turn(cleaned)
            if self._on_event is not None:
                self._seq += 1
                self._on_event(
                    {
                        "type": "transcript",
                        "id": f"user-{self._seq}",
                        "role": "user",
                        "text": cleaned,
                        "final": True,
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                )
        await self.push_frame(frame, direction)


class AssistantEventsObserver(FrameProcessor):
    """
    Captures Gemini response text frames and user VAD speaking state
    to emit live assistant transcripts and speaking indicators.
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
            self._emit({"type": "activity", "speaker": "user", "speaking": True})
        elif isinstance(frame, UserStoppedSpeakingFrame):
            self._emit({"type": "activity", "speaker": "user", "speaking": False})
        elif isinstance(frame, LLMFullResponseStartFrame):
            self._turn_seq += 1
            self._current_turn_id = f"assistant-{self._turn_seq}"
            self._buffer = ""
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
                self._on_event({"type": "activity", "speaker": "assistant", "speaking": True})
            elif isinstance(frame, BotStoppedSpeakingFrame):
                self._on_event({"type": "activity", "speaker": "assistant", "speaking": False})
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
            vad_analyzer=SileroVADAnalyzer(),
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
