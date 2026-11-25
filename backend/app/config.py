"""Application configuration loaded safely from environment variables."""

from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent

PLACEHOLDER_PREFIXES = ("your_", "changeme", "replace_")


class Settings(BaseSettings):
    """Central settings object for the MediVoice AI backend."""

    model_config = SettingsConfigDict(
        env_file=(str(ROOT_DIR / ".env"), str(BACKEND_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    cors_origins: str = "http://localhost:3000"
    database_url: str = "sqlite:///./medivoice.db"

    # AI and voice provider keys (configured for Phase 2+)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    voice_ice_servers: str = "stun:stun.l.google.com:19302"

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse comma-separated CORS origins into a clean list."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def ice_servers_list(self) -> list[str]:
        """Parse comma-separated STUN/TURN URLs for WebRTC."""
        return [url.strip() for url in self.voice_ice_servers.split(",") if url.strip()]

    @staticmethod
    def is_secret_configured(value: str) -> bool:
        """Return True only when a non-placeholder value is provided."""
        cleaned = value.strip()
        if not cleaned:
            return False
        return not cleaned.lower().startswith(PLACEHOLDER_PREFIXES)

    def missing_voice_env_vars(self) -> list[str]:
        """Return names of missing or placeholder voice credentials."""
        required = {
            "GEMINI_API_KEY": self.gemini_api_key,
            "ELEVENLABS_API_KEY": self.elevenlabs_api_key,
            "ELEVENLABS_VOICE_ID": self.elevenlabs_voice_id,
        }
        return [name for name, val in required.items() if not self.is_secret_configured(val)]


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
