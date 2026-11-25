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
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse comma-separated CORS origins into a clean list."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @staticmethod
    def is_secret_configured(value: str) -> bool:
        """Return True only when a non-placeholder value is provided."""
        cleaned = value.strip()
        if not cleaned:
            return False
        return not cleaned.lower().startswith(PLACEHOLDER_PREFIXES)


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
