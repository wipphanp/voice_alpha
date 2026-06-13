"""
Custom Sarvam AI plugins for LiveKit Agents.

These implement the STT and TTS interfaces using Sarvam's REST API.
If/when an official livekit-plugins-sarvam package becomes available,
these can be replaced with the official implementations.
"""

from .stt import SarvamSTT
from .tts import SarvamTTS

__all__ = ["SarvamSTT", "SarvamTTS"]
