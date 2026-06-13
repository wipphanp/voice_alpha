"""
Sarvam AI Speech-to-Text plugin for LiveKit Agents.

Uses Sarvam Saaras v2 API for native Hindi/Hinglish/Marathi transcription.
API Docs: https://docs.sarvam.ai/api-reference-docs/speech-to-text
"""

import io
import logging
import wave
from dataclasses import dataclass

import aiohttp

from livekit.agents import stt, utils

from app.config.settings import settings

logger = logging.getLogger(__name__)

SARVAM_STT_URL = "https://api.sarvam.ai/speech-to-text"


@dataclass
class SarvamSTTOptions:
    language_code: str = "hi-IN"
    model: str = "saaras:v2"


class SarvamSTT(stt.STT):
    """
    Sarvam Saaras STT — native Indian language speech recognition.

    Supports: hi-IN, en-IN, mr-IN, ta-IN, te-IN, kn-IN, ml-IN, gu-IN,
              bn-IN, pa-IN, od-IN, and 'unknown' for auto-detection.
    """

    def __init__(
        self,
        *,
        language_code: str = "hi-IN",
        model: str = "saaras:v2",
        api_key: str | None = None,
    ):
        super().__init__(
            capabilities=stt.STTCapabilities(streaming=False, interim_results=False)
        )
        self._api_key = api_key or settings.sarvam_api_key
        self._opts = SarvamSTTOptions(
            language_code=language_code,
            model=model,
        )
        self._session: aiohttp.ClientSession | None = None

    def set_language(self, language_code: str) -> None:
        """
        Switch the STT language at runtime (called by switch_language tool).

        This immediately takes effect on the next transcription request,
        ensuring accurate recognition when the customer switches language
        mid-conversation (e.g., Hindi -> Marathi).

        Args:
            language_code: Sarvam STT language code (e.g., 'hi-IN', 'mr-IN', 'en-IN', 'unknown')
        """
        old_lang = self._opts.language_code
        self._opts.language_code = language_code
        logger.info("STT language switched: %s -> %s", old_lang, language_code)

    @property
    def current_language(self) -> str:
        """Return the currently active STT language code."""
        return self._opts.language_code

    def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _recognize_impl(
        self,
        buffer: utils.AudioBuffer,
        *,
        language=None,
        conn_options=None,
    ) -> stt.SpeechEvent:
        """Send audio to Sarvam STT API via multipart form upload."""
        session = self._ensure_session()

        # Convert audio buffer to WAV bytes
        wav_bytes = _audio_buffer_to_wav(buffer)

        lang = language or self._opts.language_code

        # Sarvam STT expects multipart/form-data with a 'file' field
        form_data = aiohttp.FormData()
        form_data.add_field(
            "file",
            wav_bytes,
            filename="audio.wav",
            content_type="audio/wav",
        )
        form_data.add_field("model", self._opts.model)
        form_data.add_field("language_code", lang)
        form_data.add_field("with_timestamps", "false")

        headers = {
            "api-subscription-key": self._api_key,
        }

        try:
            async with session.post(
                SARVAM_STT_URL, data=form_data, headers=headers
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error("Sarvam STT error (%d): %s", resp.status, error_text)
                    return stt.SpeechEvent(
                        type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                        alternatives=[stt.SpeechData(text="", language=lang)],
                    )

                data = await resp.json()
                transcript = data.get("transcript", "")

                logger.debug("STT result: '%s'", transcript)

                return stt.SpeechEvent(
                    type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                    alternatives=[
                        stt.SpeechData(
                            text=transcript,
                            language=lang,
                            confidence=1.0,
                        )
                    ],
                )

        except Exception as e:
            logger.error("Sarvam STT request failed: %s", e)
            return stt.SpeechEvent(
                type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                alternatives=[stt.SpeechData(text="", language=lang)],
            )

    async def aclose(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()


def _audio_buffer_to_wav(buffer: utils.AudioBuffer) -> bytes:
    """Convert LiveKit AudioBuffer to WAV bytes."""
    frame = buffer.data
    sample_rate = buffer.sample_rate
    num_channels = buffer.num_channels

    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(num_channels)
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(frame)

    return output.getvalue()
