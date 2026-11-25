"""FastAPI entry point for MediVoice AI."""

from contextlib import asynccontextmanager
import sys
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routes.appointments import router as appointments_router
from app.routes.doctors import router as doctors_router
from app.seed import init_db

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Initialize SQLite tables and seed mock doctors on application startup."""
    init_db()
    yield


app = FastAPI(
    title="MediVoice AI Backend",
    description="Voice-Based Doctor Appointment Assistant API",
    version="0.3.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(doctors_router)
app.include_router(appointments_router)


@app.get("/")
def read_root():
    """Return basic service metadata."""
    return {
        "service": "MediVoice AI Backend",
        "phase": "Phase 1 - Foundation",
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health")
def health_check():
    """Report real server health and non-secret environment readiness."""
    return {
        "status": "ok",
        "service": "medivoice-backend",
        "phase": "Phase 1 - Foundation",
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "database_configured": bool(settings.database_url.strip()),
        "env_keys": {
            "gemini_api_key": settings.is_secret_configured(settings.gemini_api_key),
            "elevenlabs_api_key": settings.is_secret_configured(settings.elevenlabs_api_key),
            "elevenlabs_voice_id": settings.is_secret_configured(settings.elevenlabs_voice_id),
        },
    }
