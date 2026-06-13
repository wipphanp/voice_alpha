"""Configuration module for the voice agent application."""

from .settings import settings
from .constants import (
    COMPANY_NAME,
    COMPANY_PHONE,
    COMPANY_EMAIL,
    COMPANY_WEBSITE,
    SUBSCRIPTION_FACTS,
    RISK_DISCLAIMER,
    SUPPORTED_LANGUAGES,
    DEFAULT_LANGUAGE,
    DEFAULT_TTS_SPEAKER,
    GREETINGS,
    SILENCE_PROMPTS,
    WRAPUP_PROMPTS,
)

__all__ = [
    "settings",
    "COMPANY_NAME",
    "COMPANY_PHONE",
    "COMPANY_EMAIL",
    "COMPANY_WEBSITE",
    "SUBSCRIPTION_FACTS",
    "RISK_DISCLAIMER",
    "SUPPORTED_LANGUAGES",
    "DEFAULT_LANGUAGE",
    "DEFAULT_TTS_SPEAKER",
    "GREETINGS",
    "SILENCE_PROMPTS",
    "WRAPUP_PROMPTS",
]
