"""
Call Recording — Single-timeline mono recording of full conversation.

Records both agent and customer audio into ONE sequential mono buffer
in real-time order. The result sounds like listening to a natural phone
call — agent speaks, customer responds, back and forth.

The recording runs natively at 24kHz to match the agent TTS sample rate,
so the agent voice needs NO resampling (zero artifacts). The customer
audio is resampled to 24kHz by LiveKit's high-quality internal resampler.

Output: 24kHz, 16-bit, mono WAV.
"""

import asyncio
import array
import json
import logging
import threading
import time
import wave
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from livekit import rtc

from app.config.settings import settings

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
RECORDINGS_DIR = settings.data_dir / "recordings"
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

# Record at 24kHz — matches agent TTS natively, so no agent-side resampling.
SAMPLE_RATE = 24000
SAMPLE_WIDTH = 2  # 16-bit PCM

# Guards concurrent writes to recordings_meta.json now that the final render
# runs in worker threads (two calls ending at once could otherwise race).
_META_LOCK = threading.Lock()

# numpy massively speeds up the final mixdown. It's present transitively
# (via livekit/silero) and declared in requirements.txt, but we keep a pure
# Python fallback so recording never breaks if it's somehow unavailable.
try:
    import numpy as _np
    _NUMPY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _NUMPY_AVAILABLE = False


class LocalCallRecorder:
    """
    Single-timeline conversation recorder at 24kHz.

    Both agent and customer audio go into ONE buffer in chronological order.
    - Agent TTS is already 24kHz → stored as-is (no resampling, no artifacts).
    - Customer audio is resampled to 24kHz by LiveKit's AudioStream (high quality).

    Uses time.monotonic() to place each chunk at the correct timeline position
    so both voices interleave naturally like a real phone call.
    """

    def __init__(self, room_name: str, customer_phone: str):
        self._room_name = room_name
        self._customer_phone = customer_phone
        self._recording = False
        self._start_time: datetime | None = None
        self._start_mono: float = 0.0
        self._file_path: Path | None = None
        self._tasks: list[asyncio.Task] = []

        # Single timeline buffer: list of (start_sample_index, pcm_bytes)
        self._timeline: list[tuple[int, bytes]] = []
        self._lock = asyncio.Lock()

        # Independent write cursors (in samples) for each speaker so each
        # stream is laid down contiguously (no self-overlap, no gaps inside
        # a single utterance). Anchored to the conversation clock on new turns.
        self._customer_pos = 0
        self._agent_pos = 0

    @property
    def file_path(self) -> Path | None:
        return self._file_path

    @property
    def is_recording(self) -> bool:
        return self._recording

    def start(self, room: rtc.Room) -> None:
        """Start recording."""
        self._recording = True
        self._start_time = datetime.now(IST)
        self._start_mono = time.monotonic()
        self._timeline = []
        self._customer_pos = 0
        self._agent_pos = 0

        # Capture remote tracks (customer)
        for participant in room.remote_participants.values():
            for pub in participant.track_publications.values():
                if pub.track and pub.track.kind == rtc.TrackKind.KIND_AUDIO:
                    task = asyncio.create_task(
                        self._capture_customer(pub.track, participant.identity)
                    )
                    self._tasks.append(task)

        @room.on("track_subscribed")
        def _on_track_subscribed(track, publication, participant):
            if track.kind == rtc.TrackKind.KIND_AUDIO and self._recording:
                task = asyncio.create_task(
                    self._capture_customer(track, participant.identity)
                )
                self._tasks.append(task)

        logger.info("Recording started (mono 24kHz timeline): %s", self._room_name)

    def _current_sample_pos(self) -> int:
        """Get current position in samples (24kHz) from recording start."""
        return int((time.monotonic() - self._start_mono) * SAMPLE_RATE)

    async def _capture_customer(self, track: rtc.Track, identity: str) -> None:
        """
        Capture customer audio into the shared timeline.
        LiveKit's AudioStream resamples the WebRTC audio to 24kHz with a
        proper anti-aliasing resampler (much cleaner than manual interpolation).

        Customer audio arrives in real time, so each frame is written
        contiguously. If there was a gap (silence while the agent spoke),
        the cursor jumps forward to the current wall-clock position.
        """
        logger.debug("Recording customer: %s", identity)
        try:
            stream = rtc.AudioStream(
                track, sample_rate=SAMPLE_RATE, num_channels=1
            )
            async for event in stream:
                if not self._recording:
                    break
                if hasattr(event, "frame") and event.frame:
                    pcm = event.frame.data.tobytes()
                    n_samples = len(pcm) // SAMPLE_WIDTH
                    async with self._lock:
                        clock = self._current_sample_pos()
                        # If our write cursor fell behind the wall clock (a
                        # gap of silence), jump forward so timing stays right.
                        if self._customer_pos < clock:
                            self._customer_pos = clock
                        self._timeline.append((self._customer_pos, pcm))
                        self._customer_pos += n_samples
        except Exception as e:
            logger.debug("Customer capture ended (%s): %s", identity, e)

    def add_agent_audio(self, pcm_data: bytes, source_rate: int = 24000) -> None:
        """
        Add agent TTS audio into the shared timeline.
        TTS is already 24kHz → stored natively with NO resampling (zero artifacts).

        Streaming TTS delivers audio FASTER than real time, so chunks must be
        written CONTIGUOUSLY (back-to-back by their own length) — never at the
        arrival timestamp, which would crush them on top of each other and
        produce garbled, overlapping audio.
        """
        if not (self._recording and pcm_data):
            return
        if source_rate != SAMPLE_RATE:
            pcm_data = _resample_pcm(pcm_data, source_rate, SAMPLE_RATE)

        n_samples = len(pcm_data) // SAMPLE_WIDTH
        clock = self._current_sample_pos()
        # New utterance: if the agent cursor is behind the wall clock, this is
        # a fresh turn — anchor it to "now". Otherwise continue contiguously.
        if self._agent_pos < clock:
            self._agent_pos = clock
        self._timeline.append((self._agent_pos, pcm_data))
        self._agent_pos += n_samples

    async def stop(self) -> str | None:
        """Stop recording, render timeline to mono WAV.

        The CPU-heavy mixdown is offloaded to a worker thread so it never
        blocks the agent's async event loop (which would stall other calls).
        """
        self._recording = False

        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        await asyncio.sleep(0.2)

        if not self._timeline:
            logger.warning("No audio captured for room: %s", self._room_name)
            return None

        logger.info("Rendering %d audio segments to timeline", len(self._timeline))

        # Generate filename
        ts = self._start_time.strftime("%Y%m%d_%H%M%S") if self._start_time else "unknown"
        phone = self._customer_phone.replace("+", "").replace(" ", "")
        filename = f"call_{phone}_{ts}.wav"
        self._file_path = RECORDINGS_DIR / filename

        # Hand the timeline to a worker thread for the mixdown + WAV write.
        timeline = self._timeline
        file_path = self._file_path
        try:
            duration_seconds = await asyncio.to_thread(
                _render_timeline_to_wav, timeline, file_path
            )
        except Exception as e:
            logger.error("Failed to save recording: %s", e)
            self._timeline.clear()
            return None

        if duration_seconds is None:
            self._timeline.clear()
            return None

        file_size_mb = self._file_path.stat().st_size / (1024 * 1024)
        logger.info(
            "Recording saved: %s (%.1fs, %.1f MB, mono 24kHz)",
            self._file_path.name, duration_seconds, file_size_mb,
        )

        self._save_metadata(duration_seconds)
        self._timeline.clear()

        return str(self._file_path)

    def _save_metadata(self, duration: float) -> None:
        metadata = {
            "room_name": self._room_name,
            "customer_phone": self._customer_phone,
            "file_path": str(self._file_path),
            "filename": self._file_path.name if self._file_path else "",
            "duration_seconds": round(duration, 1),
            "recorded_at": self._start_time.isoformat() if self._start_time else "",
            "sample_rate": SAMPLE_RATE,
            "channels": 1,
            "format": "mono (agent+customer interleaved timeline)",
            "bit_depth": 16,
        }

        # Lock + atomic write: concurrent call-ends may write this file from
        # different worker threads.
        meta_file = settings.data_dir / "recordings_meta.json"
        with _META_LOCK:
            existing = []
            if meta_file.exists():
                try:
                    existing = json.loads(meta_file.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    existing = []
            existing.append(metadata)
            tmp = meta_file.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            tmp.replace(meta_file)


def _render_timeline_to_wav(timeline: list[tuple[int, bytes]], file_path: Path) -> float | None:
    """
    Mix all timeline segments into one mono buffer and write a 24kHz WAV.

    Runs in a worker thread (never on the event loop). Uses numpy when
    available for a fast vectorized mixdown, with a pure-Python fallback that
    reproduces the same algorithm: int32 accumulation for overlaps, clip to
    int16, then −3dB peak normalization.

    Returns the duration in seconds, or None if there was nothing to render.
    """
    if not timeline:
        return None

    # Total length = furthest segment end.
    max_end = 0
    for pos, pcm in timeline:
        end = pos + len(pcm) // SAMPLE_WIDTH
        if end > max_end:
            max_end = end

    total_samples = max_end
    if total_samples <= 0:
        return None
    duration_seconds = total_samples / SAMPLE_RATE

    if _NUMPY_AVAILABLE:
        output_bytes = _mixdown_numpy(timeline, total_samples)
    else:  # pragma: no cover - fallback path
        output_bytes = _mixdown_python(timeline, total_samples)

    with wave.open(str(file_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(output_bytes)

    return duration_seconds


def _mixdown_numpy(timeline: list[tuple[int, bytes]], total_samples: int) -> bytes:
    """Vectorized mixdown using numpy. int32 accumulator handles overlaps."""
    accum = _np.zeros(total_samples, dtype=_np.int32)

    for pos, pcm in timeline:
        # Trim odd trailing byte to stay 16-bit aligned.
        if len(pcm) % 2 != 0:
            pcm = pcm[:-1]
        if not pcm:
            continue
        seg = _np.frombuffer(pcm, dtype=_np.int16).astype(_np.int32)
        end = pos + seg.shape[0]
        if end > total_samples:
            seg = seg[: total_samples - pos]
            end = total_samples
        if pos < 0:
            seg = seg[-pos:]
            pos = 0
        accum[pos:end] += seg

    # Clip to int16 range.
    _np.clip(accum, -32768, 32767, out=accum)

    # −3dB peak normalization (mirrors the pure-Python _normalize).
    peak = int(_np.max(_np.abs(accum))) if accum.size else 0
    if peak >= 100:
        gain = min(23197 / peak, 4.0)  # 23197 ≈ -3 dB of full scale
        if not (0.95 <= gain <= 1.05):
            scaled = (accum.astype(_np.float64) * gain)
            _np.clip(scaled, -32768, 32767, out=scaled)
            accum = scaled.astype(_np.int32)

    return accum.astype("<i2").tobytes()


def _mixdown_python(timeline: list[tuple[int, bytes]], total_samples: int) -> bytes:
    """Pure-Python fallback mixdown (slow, used only if numpy is missing)."""
    accum = [0] * total_samples

    for pos, pcm in timeline:
        samples = array.array("h")
        samples.frombytes(pcm if len(pcm) % 2 == 0 else pcm[:-1])
        for i, sample in enumerate(samples):
            idx = pos + i
            if 0 <= idx < total_samples:
                accum[idx] += sample

    output = array.array("h")
    for val in accum:
        output.append(max(-32768, min(32767, val)))

    output = _normalize(output)
    return output.tobytes()


def _resample_pcm(pcm_data: bytes, src_rate: int, dst_rate: int) -> bytes:
    """
    Resample 16-bit mono PCM between sample rates using linear interpolation.
    Only used as a fallback if agent audio ever arrives at a non-24kHz rate.
    """
    if src_rate == dst_rate or not pcm_data:
        return pcm_data

    src = array.array("h")
    src.frombytes(pcm_data if len(pcm_data) % 2 == 0 else pcm_data[:-1])
    if len(src) == 0:
        return pcm_data

    ratio = dst_rate / src_rate
    out_len = int(len(src) * ratio)
    out = array.array("h", [0]) * out_len

    for i in range(out_len):
        src_pos = i / ratio
        idx = int(src_pos)
        frac = src_pos - idx
        if idx + 1 < len(src):
            val = src[idx] * (1 - frac) + src[idx + 1] * frac
        else:
            val = src[idx]
        out[i] = max(-32768, min(32767, int(val)))

    return out.tobytes()


def _normalize(samples: array.array) -> array.array:
    """Normalize to -3 dB peak."""
    if not samples:
        return samples

    peak = max(abs(s) for s in samples)
    if peak < 100:
        return samples

    target = 23197  # -3 dB
    gain = target / peak
    gain = min(gain, 4.0)

    if 0.95 <= gain <= 1.05:
        return samples

    result = array.array("h")
    for s in samples:
        result.append(max(-32768, min(32767, int(s * gain))))
    return result


def get_recordings() -> list[dict]:
    """Get all recording metadata."""
    meta_file = settings.data_dir / "recordings_meta.json"
    if meta_file.exists():
        try:
            return json.loads(meta_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    recordings = []
    if RECORDINGS_DIR.exists():
        for wav_file in sorted(RECORDINGS_DIR.glob("*.wav")):
            recordings.append({
                "filename": wav_file.name,
                "file_path": str(wav_file),
                "size_bytes": wav_file.stat().st_size,
            })
    return recordings
