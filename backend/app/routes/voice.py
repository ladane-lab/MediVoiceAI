"""FastAPI endpoints for Pipecat SmallWebRTC voice sessions."""

from fastapi import APIRouter, Depends, HTTPException, status

from app.schemas import (
    VoiceIcePatchRequest,
    VoiceOfferRequest,
    VoiceOfferResponse,
    VoiceSessionCreateResponse,
    VoiceSessionEndResponse,
    VoiceSessionStateSummary,
    VoiceStatusResponse,
)
from app.voice.agent import VoiceConfigurationError
from app.voice.session import VoiceSessionManager

router = APIRouter(prefix="/api/voice", tags=["Voice"])

_session_manager: VoiceSessionManager | None = None


def get_voice_session_manager() -> VoiceSessionManager:
    """Return the singleton VoiceSessionManager instance."""
    global _session_manager
    if _session_manager is None:
        _session_manager = VoiceSessionManager()
    return _session_manager


@router.get("/status", response_model=VoiceStatusResponse)
def voice_status(manager: VoiceSessionManager = Depends(get_voice_session_manager)):
    """Report voice pipeline configuration readiness and active session count."""
    return manager.get_status()


@router.post(
    "/sessions",
    response_model=VoiceSessionCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_voice_session(manager: VoiceSessionManager = Depends(get_voice_session_manager)):
    """Validate voice API credentials and pre-register a WebRTC session."""
    try:
        return manager.create_session()
    except VoiceConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@router.get("/sessions/{session_id}", response_model=VoiceSessionStateSummary)
def get_voice_session(
    session_id: str,
    manager: VoiceSessionManager = Depends(get_voice_session_manager),
):
    """Return non-sensitive session and confirmation gate status."""
    summary = manager.get_session_summary(session_id)
    if not summary:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Voice session '{session_id}' was not found.",
        )
    return summary


@router.post("/offer", response_model=VoiceOfferResponse)
async def webrtc_offer(
    payload: VoiceOfferRequest,
    manager: VoiceSessionManager = Depends(get_voice_session_manager),
):
    """Negotiate a browser WebRTC SDP offer and attach the Pipecat voice pipeline."""
    try:
        return await manager.handle_offer(
            sdp=payload.sdp,
            sdp_type=payload.type,
            pc_id=payload.pc_id,
            restart_pc=payload.restart_pc,
            session_id=payload.session_id,
        )
    except VoiceConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to establish WebRTC voice connection.",
        ) from exc


@router.patch("/offer", status_code=status.HTTP_204_NO_CONTENT)
async def webrtc_ice_patch(
    payload: VoiceIcePatchRequest,
    manager: VoiceSessionManager = Depends(get_voice_session_manager),
):
    """Handle trickle ICE candidates for an active SmallWebRTC connection."""
    try:
        await manager.handle_ice_patch(
            pc_id=payload.pc_id,
            candidates=[c.model_dump() for c in payload.candidates],
        )
    except VoiceConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to apply ICE candidate update.",
        ) from exc


@router.post("/sessions/{session_id}/end", response_model=VoiceSessionEndResponse)
async def end_voice_session(
    session_id: str,
    manager: VoiceSessionManager = Depends(get_voice_session_manager),
):
    """Terminate an active voice session and close its WebRTC connection."""
    result = await manager.end_session(session_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Voice session '{session_id}' was not found.",
        )
    return result
