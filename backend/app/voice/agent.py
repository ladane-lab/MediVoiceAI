"""Pipecat voice pipeline assembly using SmallWebRTC, ElevenLabs, Silero VAD, and Google Gemini."""

from dataclasses import dataclass
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import Frame, TranscriptionFrame
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
    """Observes final STT transcripts so conversation confirmation gates track real user turns."""

    def __init__(self, state: VoiceConversationState):
        super().__init__()
        self._state = state

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, TranscriptionFrame) and frame.text.strip():
            self._state.record_user_turn(frame.text)
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
) -> VoicePipelineBundle:
    """
    Construct a real-time Pipecat audio pipeline for a browser WebRTC connection.

    Pipeline flow:
    Browser Audio -> SmallWebRTC Input -> ElevenLabs Realtime STT -> Transcript Observer
    -> User Aggregator (Silero VAD) -> Google Gemini LLM (Function Calling)
    -> ElevenLabs TTS -> SmallWebRTC Output -> Assistant Aggregator
    """
    validate_voice_configuration(settings)
    session_state = state or VoiceConversationState()
    system_prompt = build_system_prompt()
    tools = build_voice_tools(session_state)

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

    transcript_observer = UserTurnTranscriptObserver(session_state)

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            transcript_observer,
            context_aggregator.user(),
            llm,
            tts,
            transport.output(),
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
