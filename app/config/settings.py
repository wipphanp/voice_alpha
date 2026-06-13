"""
Application settings loaded from environment variables.
Uses pydantic-settings for validation and type safety.
"""

import os
from pathlib import Path
from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator


class Settings(BaseSettings):
    """Central configuration — all values sourced from .env file."""

    # ─── LiveKit ───────────────────────────────────────────────────────
    livekit_url: str = Field(..., description="LiveKit Cloud WebSocket URL")
    livekit_api_key: str = Field(..., description="LiveKit API Key")
    livekit_api_secret: str = Field(..., description="LiveKit API Secret")

    # ─── Sarvam AI ─────────────────────────────────────────────────────
    sarvam_api_key: str = Field(..., description="Sarvam AI API Key")

    # ─── Deepgram (streaming STT) ─────────────────────────────────────
    deepgram_api_key: str = Field(default="", description="Deepgram API Key for streaming STT")
    stt_provider: str = Field(default="sarvam", description="STT provider: deepgram or sarvam")

    # ─── OpenAI (optional if using Sarvam LLM) ────────────────────────
    openai_api_key: str = Field(default="", description="OpenAI API Key")

    # ─── SIP / Telephony (optional — not needed for browser WebRTC) ──
    sip_outbound_trunk_id: str = Field(default="", description="LiveKit SIP Trunk ID (optional for browser-only mode)")

    # ─── Voice Configuration ──────────────────────────────────────────
    sarvam_tts_speaker: str = Field(default="ritu", description="Sarvam TTS voice")
    default_language: str = Field(default="en-IN", description="Default language code")
    use_sarvam_llm: bool = Field(default=False, description="Use Sarvam sarvam-30b LLM")

    # ─── Server ───────────────────────────────────────────────────────
    port: int = Field(default=8000, description="FastAPI server port")
    host: str = Field(default="0.0.0.0", description="Server bind host")
    debug: bool = Field(default=False, description="Enable debug mode")

    @field_validator("debug", mode="before")
    @classmethod
    def _parse_debug(cls, value):
        """Accept env-style strings like `release` without failing startup."""
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "prod", "production", "false", "0", "off", "no"}:
                return False
            if normalized in {"debug", "dev", "development", "true", "1", "on", "yes"}:
                return True
        return value

    # ─── Security (all opt-in — empty/defaults preserve current behavior) ──
    api_auth_token: str = Field(
        default="",
        description="If set, all /api routes + dashboard require this token "
        "(X-API-Key header, Bearer token, or ?token= query param). "
        "Empty = auth disabled (logs a warning at startup).",
    )
    allowed_origins: str = Field(
        default="",
        description="Comma-separated CORS origins. Empty = localhost only on "
        "the configured port.",
    )
    call_rate_limit_per_minute: int = Field(
        default=20,
        description="Max outbound-call trigger requests per minute "
        "(POST /api/call and /api/call/batch). 0 = unlimited.",
    )

    # ─── Data Storage ─────────────────────────────────────────────────
    data_dir: Path = Field(
        default=Path(__file__).parent.parent.parent / "data",
        description="Directory for JSON data files",
    )

    # ─── WhatsApp Integration (optional — stub mode if not set) ───────
    whatsapp_api_key: str = Field(default="", description="WhatsApp API key (Twilio/Plivo)")
    whatsapp_phone_number: str = Field(default="", description="WhatsApp sender phone number")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()


# Module-level convenience
settings = get_settings()
