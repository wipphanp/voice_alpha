"""
Sarvam AI Text-to-Speech plugin for LiveKit Agents.

Uses Sarvam Bulbul v3 REST API at 48kHz for clear audio output.
Optimized for low first-byte latency with persistent HTTP connections.
"""

import base64
import io
import logging
import uuid
import wave
from dataclasses import dataclass

import aiohttp

from livekit.agents import tts, APIConnectOptions

from app.config.settings import settings

logger = logging.getLogger(__name__)

SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"
SARVAM_TTS_STREAM_URL = "https://api.sarvam.ai/text-to-speech/stream"


@dataclass
class SarvamTTSOptions:
    model: str = "bulbul:v3"
    target_language_code: str = "hi-IN"
    speaker: str = "shubh"
    pace: float = 1.2
    speech_sample_rate: int = 8000
    enable_preprocessing: bool = True


# ─── Per-language natural pace values ─────────────────────────────────────
# Each Indian language has a distinct natural speaking rhythm. These values
# are tuned to sound like a native speaker having a real phone conversation
# — not too fast (robotic), not too slow (unnatural pauses).
LANGUAGE_PACE = {
    "hi-IN": 1.15,   # Hindi — natural Delhi/Mumbai conversational pace
    "en-IN": 1.15,   # Indian English — natural and crisp
    "kn-IN": 1.10,   # Kannada — relaxed Bengaluru native speech rhythm
    "te-IN": 1.10,   # Telugu — natural Hyderabadi conversational flow
    "ml-IN": 1.05,   # Malayalam — measured Kerala native rhythm (slightly slower)
    "ta-IN": 1.10,   # Tamil — natural Chennai conversational flow
    "mr-IN": 1.15,   # Marathi — natural Pune/Mumbai rhythm
    "hi-EN": 1.15,   # Hinglish
    "unknown": 1.15,
}


class SarvamTTS(tts.TTS):
    """
    Sarvam Bulbul v3 TTS — optimized for low-latency voice delivery.
    Uses persistent HTTP connection pool to eliminate cold-start jitter.
    """

    def __init__(
        self,
        *,
        model: str = "bulbul:v3",
        target_language_code: str = "hi-IN",
        speaker: str = "shubh",
        pace: float | None = None,   # None = auto-select from LANGUAGE_PACE
        speech_sample_rate: int = 8000,
        enable_preprocessing: bool = True,
        api_key: str | None = None,
    ):
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=speech_sample_rate,
            num_channels=1,
        )
        self._api_key = api_key or settings.sarvam_api_key
        # Use language-specific natural pace if caller doesn't specify one
        resolved_pace = pace if pace is not None else LANGUAGE_PACE.get(target_language_code, 1.20)
        self._opts = SarvamTTSOptions(
            model=model,
            target_language_code=target_language_code,
            speaker=speaker,
            pace=resolved_pace,
            speech_sample_rate=speech_sample_rate,
            enable_preprocessing=enable_preprocessing,
        )
        # Persistent session with connection pooling and keep-alive
        # This eliminates TCP/TLS handshake on subsequent requests
        self._connector = aiohttp.TCPConnector(
            limit=8,              # Up to 8 concurrent connections (faster parallel chunks)
            keepalive_timeout=120, # Keep connections alive for 120s (reuse across turns)
            enable_cleanup_closed=True,
        )
        self._session: aiohttp.ClientSession | None = None
        self._recorder = None  # Call recorder reference

    def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                connector=self._connector,
                connector_owner=False,  # Don't close connector when session closes
                timeout=aiohttp.ClientTimeout(total=10, connect=3),  # Tighter timeout for faster failover
            )
        return self._session

    def set_language(self, language_code: str) -> None:
        """
        Switch the TTS output language at runtime (called by switch_language tool).
        Also updates the pace to the natural speaking pace for that language.

        Args:
            language_code: Sarvam TTS language code (e.g., 'hi-IN', 'kn-IN', 'en-IN')
        """
        old_lang = self._opts.target_language_code
        self._opts.target_language_code = language_code
        # Update pace to the natural pace for the new language
        self._opts.pace = LANGUAGE_PACE.get(language_code, 1.20)
        logger.info(
            "TTS language switched: %s -> %s (pace: %.2f)",
            old_lang, language_code, self._opts.pace,
        )

    @property
    def current_language(self) -> str:
        """Return the currently active TTS language code."""
        return self._opts.target_language_code

    def synthesize(self, text: str, *, conn_options=None) -> "SarvamChunkedStream":
        if conn_options is None:
            conn_options = APIConnectOptions()
        return SarvamChunkedStream(
            tts=self,
            input_text=text,
            opts=self._opts,
            api_key=self._api_key,
            session_factory=self._ensure_session,
            conn_options=conn_options,
            recorder=self._recorder,
        )

    def prewarm(self) -> None:
        """
        Pre-warm the HTTP connection to Sarvam API.
        Called synchronously by the LiveKit framework. Schedules the async
        connection in the background without blocking.
        """
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._prewarm_async())
            else:
                loop.run_until_complete(self._prewarm_async())
        except Exception as e:
            logger.debug("TTS prewarm skipped: %s", e)

    async def _prewarm_async(self) -> None:
        """Async implementation of TTS pre-warm — establishes HTTP connection."""
        session = self._ensure_session()
        try:
            async with session.post(
                SARVAM_TTS_STREAM_URL,
                json={
                    "text": "hello",
                    "target_language_code": "kn-IN",
                    "speaker": self._opts.speaker,
                    "model": self._opts.model,
                    "speech_sample_rate": self._opts.speech_sample_rate,
                    "output_audio_codec": "linear16",
                },
                headers={
                    "Content-Type": "application/json",
                    "api-subscription-key": self._api_key,
                },
            ) as resp:
                await resp.read()
                logger.debug("TTS connection pre-warmed (status: %d, sample_rate: %d)", resp.status, self._opts.speech_sample_rate)
        except Exception as e:
            logger.debug("TTS prewarm failed (non-critical): %s", e)

    async def aclose(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        if self._connector and not self._connector.closed:
            await self._connector.close()


class SarvamChunkedStream(tts.ChunkedStream):
    """Synthesize text via Sarvam TTS REST API with optimized connection reuse."""

    def __init__(self, *, tts, input_text, opts, api_key, session_factory, conn_options, recorder=None):
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._opts = opts
        self._api_key = api_key
        self._session_factory = session_factory
        self._recorder = recorder

    async def _run(self, output_emitter) -> None:
        request_id = str(uuid.uuid4())
        output_emitter.initialize(
            request_id=request_id,
            sample_rate=self._opts.speech_sample_rate,
            num_channels=1,
            mime_type="audio/pcm",
        )

        session = self._session_factory()
        text = self.input_text.strip()
        if not text:
            return

        headers = {
            "Content-Type": "application/json",
            "api-subscription-key": self._api_key,
        }

        # Use streaming endpoint with linear16 (raw PCM) — chunks arrive
        # progressively as audio is generated, slashing time-to-first-audio.
        payload = {
            "text": text,
            "target_language_code": _resolve_tts_language(self._opts.target_language_code),
            "speaker": self._opts.speaker,
            "model": self._opts.model,
            "pace": self._opts.pace,
            "speech_sample_rate": self._opts.speech_sample_rate,
            "output_audio_codec": "linear16",
            "enable_preprocessing": self._opts.enable_preprocessing,
        }

        try:
            await self._run_streaming(session, payload, headers, output_emitter)
        except Exception as e:
            # Fall back to non-streaming REST endpoint on any streaming failure
            logger.warning("Streaming TTS failed (%s) — falling back to REST", e)
            await self._run_rest(session, payload, headers, output_emitter)

    async def _run_streaming(self, session, payload, headers, output_emitter) -> None:
        """Stream raw PCM audio chunks from Sarvam streaming endpoint."""
        first_chunk = True
        total_bytes = 0
        leftover = b""  # carry odd byte across chunks (16-bit alignment)

        async with session.post(
            SARVAM_TTS_STREAM_URL, json=payload, headers=headers
        ) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                from livekit.agents._exceptions import APIError
                raise APIError(f"Sarvam stream TTS {resp.status}: {error_text}")

            # Smaller chunks (512 bytes) = lowest time-to-first-audio possible
            async for chunk in resp.content.iter_chunked(512):
                if not chunk:
                    continue

                # Skip WAV/RIFF header on the very first chunk if present
                if first_chunk and chunk[:4] == b"RIFF":
                    # WAV header is 44 bytes — strip it to get raw PCM
                    chunk = chunk[44:]
                first_chunk = False

                # Maintain 16-bit (2-byte) alignment across chunk boundaries
                data = leftover + chunk
                if len(data) % 2 != 0:
                    leftover = data[-1:]
                    data = data[:-1]
                else:
                    leftover = b""

                if data:
                    total_bytes += len(data)
                    if self._recorder and self._recorder.is_recording:
                        self._recorder.add_agent_audio(data)
                    output_emitter.push(data)

        if leftover:
            output_emitter.push(leftover + b"\x00")

        logger.debug("TTS stream: %d bytes PCM delivered progressively", total_bytes)

    async def _run_rest(self, session, payload, headers, output_emitter) -> None:
        """Fallback: non-streaming REST endpoint (base64 JSON response)."""
        rest_payload = dict(payload)
        rest_payload.pop("output_audio_codec", None)

        async with session.post(SARVAM_TTS_URL, json=rest_payload, headers=headers) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                logger.error("Sarvam TTS error (%d): %s", resp.status, error_text)
                from livekit.agents._exceptions import APIError
                raise APIError(f"Sarvam TTS returned {resp.status}: {error_text}")

            data = await resp.json()
            audio_b64 = data.get("audios", [None])[0]

            if not audio_b64:
                from livekit.agents._exceptions import APIError
                raise APIError("No audio in Sarvam TTS response")

            audio_bytes = base64.b64decode(audio_b64)

            if audio_bytes[:4] == b"RIFF":
                buf = io.BytesIO(audio_bytes)
                with wave.open(buf, "rb") as wf:
                    pcm = wf.readframes(wf.getnframes())
                    if self._recorder and self._recorder.is_recording:
                        self._recorder.add_agent_audio(pcm)
                    output_emitter.push(pcm)
            else:
                if self._recorder and self._recorder.is_recording:
                    self._recorder.add_agent_audio(audio_bytes)
                output_emitter.push(audio_bytes)


# ─── Recording hook ────────────────────────────────────────────────────
_active_recorder = None


def set_active_recorder(recorder) -> None:
    """Register a recorder to receive agent TTS audio frames."""
    global _active_recorder
    _active_recorder = recorder
    logger.debug("TTS recorder hook registered")


def clear_active_recorder() -> None:
    """Unregister the active recorder."""
    global _active_recorder
    _active_recorder = None


def _notify_recorder(pcm_data: bytes) -> None:
    """Send PCM data to the active recorder if one is set."""
    global _active_recorder
    if _active_recorder is not None:
        try:
            _active_recorder.add_agent_audio(pcm_data)
        except Exception:
            pass


def _resolve_tts_language(language_code: str) -> str:
    """Map language codes to valid Sarvam TTS language codes."""
    mapping = {
        "hi-IN": "hi-IN",
        "en-IN": "en-IN",
        "kn-IN": "kn-IN",
        "te-IN": "te-IN",
        "ml-IN": "ml-IN",
        "ta-IN": "ta-IN",
        "mr-IN": "mr-IN",
        "hi-EN": "hi-IN",
        "unknown": "hi-IN",
    }
    return mapping.get(language_code, "hi-IN")
