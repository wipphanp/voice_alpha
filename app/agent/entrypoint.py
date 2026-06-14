"""
LiveKit Agent entrypoint — configures the voice pipeline and starts the session.

Pipeline: Silero VAD → STT (Deepgram streaming or Sarvam) → GPT-4o-mini → Sarvam TTS (Bulbul v3)
Optimized for natural, low-latency conversational flow.
"""

import asyncio
import json
import logging
import re
import unicodedata

from livekit.agents import AgentSession, JobContext
from livekit.plugins import openai, silero

from app.agent.voice_agent import TradingAssistant
from app.agent.sarvam_plugins import SarvamSTT, SarvamTTS
from app.config.settings import settings
from app.core.prompt_engine import PromptEngine

# Import Deepgram at module level (plugin registration must happen on main thread)
try:
    from livekit.plugins import deepgram as deepgram_plugin
    DEEPGRAM_AVAILABLE = True
except ImportError:
    DEEPGRAM_AVAILABLE = False

logger = logging.getLogger(__name__)

LANGUAGE_SWITCH_PATTERNS = {
    "english": (
        "speak in english",
        "talk in english",
        "switch to english",
        "continue in english",
        "english only",
        "in english please",
        "english please",
        "english",
    ),
    "hindi": (
        "speak in hindi",
        "talk in hindi",
        "switch to hindi",
        "continue in hindi",
        "hindi mein",
        "hindi me",
        "hindi mai",
        "hindi bol",
        "हिंदी",
        "हिन्दी",
    ),
    "kannada": (
        "speak in kannada",
        "talk in kannada",
        "switch to kannada",
        "continue in kannada",
        "kannada alli",
        "kannada nalli",
        "kannada mat",
        "kannada maat",
        "ಕನ್ನಡ",
    ),
    "telugu": (
        "speak in telugu",
        "talk in telugu",
        "switch to telugu",
        "continue in telugu",
        "telugu lo",
        "telugu mat",
        "తెలుగు",
    ),
    "malayalam": (
        "speak in malayalam",
        "talk in malayalam",
        "switch to malayalam",
        "continue in malayalam",
        "malayalam il",
        "malayalam lo",
        "malayalathil",
        "മലയാളം",
    ),
    "tamil": (
        "speak in tamil",
        "talk in tamil",
        "switch to tamil",
        "continue in tamil",
        "tamil la",
        "tamil pes",
        "தமிழ்",
    ),
    "marathi": (
        "speak in marathi",
        "talk in marathi",
        "switch to marathi",
        "continue in marathi",
        "marathi madhe",
        "marathi bol",
        "मराठी",
    ),
}


def _normalize_transcript(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = re.sub(r"[^\w\s]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _detect_language_switch_request(transcript: str) -> str | None:
    normalized = _normalize_transcript(transcript)
    if not normalized:
        return None

    for language, patterns in LANGUAGE_SWITCH_PATTERNS.items():
        if any(pattern in normalized for pattern in patterns):
            return language
    return None


async def entrypoint(ctx: JobContext):
    """
    LiveKit Agent entrypoint — optimized for natural, low-latency voice.
    
    KEY DESIGN:
    - ALWAYS start greeting in Kannada (Winners Paradise is Bengaluru-based)
    - Ask customer for preferred LANGUAGE (but agent voice stays same)
    - Language switch = LLM language + STT language (NOT agent voice/speaker)
    - Agent speaks in consistent voice across ALL languages (humanlike)
    """
    await ctx.connect()

    # Extract customer context from room metadata
    metadata = json.loads(ctx.room.metadata or "{}")
    customer_name = metadata.get("customer_name", "Customer")
    customer_phone = metadata.get("customer_phone", "")
    # IMPORTANT: Don't use preferred_language for initial greeting — always start Kannada!
    initial_greeting_language = "kn-IN"  # Winners Paradise = Bengaluru = Kannada first
    customer_preferred_language = "kn-IN"  # Will be updated after customer responds

    logger.info(
        "Agent joining room %s for customer: %s (%s)",
        ctx.room.name,
        customer_name,
        customer_phone,
    )

    # ─── Pick agent persona (name + gender + voice) ────────────────────
    from app.config.constants import detect_customer_gender, pick_agent_persona
    customer_gender = detect_customer_gender(customer_name)
    persona = pick_agent_persona(customer_gender)
    agent_name   = persona["agent_name"]
    agent_gender = persona["agent_gender"]
    tts_speaker  = persona["tts_speaker"]  # THIS VOICE NEVER CHANGES

    logger.info(
        "Persona selected: agent=%s (%s voice), customer_gender=%s — voice stays consistent across all languages",
        agent_name, tts_speaker, customer_gender,
    )

    # Build the hydrated system prompt with customer memory + agent persona
    from app.core.memory import get_customer_history
    customer_memory = get_customer_history(customer_phone) or ""

    system_prompt = PromptEngine.get_prompt(
        customer_name=customer_name,
        customer_phone=customer_phone,
        customer_memory=customer_memory,
        agent_name=agent_name,
        agent_gender=agent_gender,
    )

    if customer_memory:
        logger.info("Loaded conversation history for %s", customer_phone)
    else:
        logger.info("No previous history for %s (first call)", customer_phone)

    # ─── Configure LLM ─────────────────────────────────────────────────
    if settings.use_sarvam_llm:
        llm_instance = openai.LLM(
            model="sarvam-30b",
            base_url="https://api.sarvam.ai/v1",
            api_key=settings.sarvam_api_key,
            temperature=0.5,  # Lower = faster, more focused responses
        )
        logger.info("Using Sarvam sarvam-30b LLM")
    else:
        llm_instance = openai.LLM(
            model="gpt-4o-mini",
            temperature=0.6,  # Lower = faster, more decisive
        )
        logger.info("Using OpenAI GPT-4o-mini LLM")

    # ─── Configure Voice Pipeline (low-latency + natural) ──────────────
    # Start with Kannada STT (will be updated on language switch)
    
    # Use BEST STT: Deepgram Nova-3 (streaming, low-latency, superior accuracy)
    # Deepgram is superior to Sarvam for Indian languages — faster, more accurate
    if DEEPGRAM_AVAILABLE:
        # Use Deepgram-specific language codes (different from Sarvam)
        deepgram_language = _resolve_deepgram_language(initial_greeting_language)
        stt_instance = deepgram_plugin.STT(
            language=deepgram_language,
            model="nova-3",  # Latest Deepgram model
        )
        logger.info("Using Deepgram Nova-3 STT (language: %s, best accuracy, lowest latency, streaming)", deepgram_language)
    else:
        # Fallback to Sarvam if Deepgram plugin not available
        sarvam_stt_language = _resolve_stt_language(initial_greeting_language)
        stt_instance = SarvamSTT(
            language_code=sarvam_stt_language,
            model="saaras:v3",
        )
        logger.info("Deepgram unavailable, using Sarvam Saaras v3 STT as fallback (language: %s)", sarvam_stt_language)

    # TTS: Use fixed agent voice (NEVER changes)
    # Language switching is ONLY in LLM + STT, not in TTS voice
    tts_instance = SarvamTTS(
        speaker=tts_speaker,           # FIXED agent voice (never changes)
        target_language_code=initial_greeting_language,  # Start in Kannada
        model="bulbul:v3",
        speech_sample_rate=8000,       # 8kHz — phone quality
        enable_preprocessing=True,     # Enable for natural speech prosody
        # pace auto-selected from language config
    )
    logger.info(
        "TTS: Fixed agent voice '%s' speaking Kannada initially "
        "(will switch language on customer request, voice stays same)",
        tts_speaker,
    )

    # Pre-warm TTS connection
    vad_instance = ctx.proc.userdata.get("vad")
    if vad_instance is None:
        logger.warning("VAD not prewarmed for this process — loading on demand")
        vad_instance = silero.VAD.load(
            min_speech_duration=0.03,    # 30ms = ultra-fast detection
            min_silence_duration=0.2,    # 200ms = quick turn boundary
            activation_threshold=0.4,    # Lower = more sensitive
        )

    session = AgentSession(
        vad=vad_instance,
        stt=stt_instance,
        llm=llm_instance,
        tts=tts_instance,
        # ─── ULTRA LOW-LATENCY tuning (maximum speed) ───────────────────
        min_endpointing_delay=0.05,    # 50ms — react INSTANTLY
        max_endpointing_delay=0.6,     # 600ms max — very fast
        preemptive_generation=True,    # start LLM before endpoint confirmed
        allow_interruptions=True,      # customer can interrupt anytime
        min_interruption_duration=0.1, # 100ms barge-in — maximum sensitivity
        min_interruption_words=1,      # at least 1 word to interrupt
        user_away_timeout=25.0,
    )

    # Language switching is handled ONLY by the switch_language tool (LLM-driven).
    # The customer must explicitly ask to change language — no automatic detection.
    # Start with Kannada, will be updated when customer chooses their language
    _current_lang = {"lang": initial_greeting_language}

    # Track call start time for duration measurement
    import time
    call_start_time = time.time()
    from pathlib import Path
    RECORDINGS_DIR = Path(settings.data_dir) / "recordings"
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

    # ─── Start local call recording ───────────────────────────────────
    from app.core.call_recorder import LocalCallRecorder
    recorder = LocalCallRecorder(
        room_name=ctx.room.name,
        customer_phone=customer_phone,
    )
    recorder.start(ctx.room)

    # Hook TTS to capture agent audio directly at the source
    tts_instance._recorder = recorder

    logger.info("Local call recording started for room: %s", ctx.room.name)

    # ─── Start conversation transcript capture ─────────────────────────
    from app.core.transcript import TranscriptRecorder
    transcript = TranscriptRecorder(
        room_name=ctx.room.name,
        customer_phone=customer_phone,
        customer_name=customer_name,
    )

    @session.on("conversation_item_added")
    def _on_conversation_item(ev):
        """Capture each finalized agent/customer turn into the transcript."""
        try:
            item = getattr(ev, "item", None)
            if item is None:
                return
            role = getattr(item, "role", None)
            text = getattr(item, "text_content", None)
            if text is None and hasattr(item, "content"):
                parts = []
                for part in (item.content or []):
                    if isinstance(part, str):
                        parts.append(part)
                    elif hasattr(part, "text"):
                        parts.append(str(part.text))
                text = " ".join(parts)
            if role and text:
                transcript.add_turn(role, text)
        except Exception as e:
            logger.debug("Transcript capture error (non-critical): %s", e)

    logger.info("Transcript capture started for room: %s", ctx.room.name)

    # ─── Agent speaks first — ALWAYS START IN KANNADA (Winners Paradise = Bengaluru) ───
    # After greeting, ask customer for preferred language
    # If customer requests language switch later, LLM + STT switch, but agent VOICE stays same
    from app.config.constants import (
        SILENCE_PROMPTS, WRAPUP_PROMPTS, UNKNOWN_NAME_PLACEHOLDERS,
    )

    name_is_unknown = customer_name.strip().lower() in UNKNOWN_NAME_PLACEHOLDERS

    # KANNADA GREETING ONLY (ALWAYS start here, Winners Paradise = Bengaluru)
    # Use NATIVE KANNADA SCRIPT for natural TTS pronunciation
    # Sarvam TTS Bulbul v3 is optimized for native Indian language scripts
    if name_is_unknown:
        kannada_greeting = (
            f"ನಮಸ್ಕಾರ! ನಾನು {agent_name}, Winners Paradise ಇಂದ. "
            f"ನಿಮಗೆ ಒಂದು ಸೂಪರ್ opportunity ಇದೆ — automatic trading bot. "
            f"ಎಲ್ಲದರಲ್ಲೂ profit ಇದೆ ಬೇ, zero tension! "
            f"ಹೌದು, ನಿಮಗೆ ಕನ್ನಡ, ಹಿಂದಿ, English, ತಮಿಳು, ತೆಲುಗು, ಮಲಯಾಳಂ, ಮರಾಠಿ — "
            f"ಯಾವುದನ್ನು prefer ಮಾಡ್ತೀರಾ?"
        )
    else:
        kannada_greeting = (
            f"{customer_name}! ನಮಸ್ಕಾರ! ನಾನು {agent_name}, Winners Paradise ಇಂದ. "
            f"ನಿಮಗೆ ಒಂದು ಸೂಪರ್ opportunity ಇದೆ — automatic trading bot. "
            f"ಎಲ್ಲದರಲ್ಲೂ profit ಇದೆ ಬೇ, zero tension! "
            f"ಹೌದು, ನಿಮಗೆ ಕನ್ನಡ, ಹಿಂದಿ, English, ತಮಿಳು, ತೆಲುಗು, ಮಲಯಾಳಂ, ಮರಾಠಿ — "
            f"ಯಾವುದನ್ನು prefer ಮಾಡ್ತೀರಾ?"
        )

    greeting_prompt = (
        f"SPEAK EXACTLY THESE WORDS IN NATIVE KANNADA SCRIPT (do not translate, do not modify, do not add, do not change): "
        f"'{kannada_greeting}' "
        f"This is pure Kannada with Bengaluru accent. Sound warm and genuine like a native Kannada speaker. "
        f"STOP immediately after saying these words and LISTEN for customer response. "
        f"DO NOT SPEAK ANY OTHER LANGUAGE."
    )

    # Create the agent FIRST before starting the session
    agent = TradingAssistant(
        customer_name=customer_name,
        customer_phone=customer_phone,
        system_prompt=system_prompt,
        stt_instance=stt_instance,
        tts_instance=tts_instance,
        job_context=ctx,
    )

    # Start the session with the agent
    await session.start(agent=agent, room=ctx.room)

    # Fire the opening greeting (Kannada + ask for language preference)
    # Non-blocking — keeps session active and listening for response
    logger.info("Triggering opening greeting via LLM (Kannada + ask for language preference)")
    session.generate_reply(instructions=greeting_prompt)

    logger.info(
        "Agent session started: room=%s agent=%s (%s voice — FIXED throughout) "
        "initial_language=Kannada (will ask for customer preference), STT=Deepgram-Nova-3",
        ctx.room.name, agent_name, tts_speaker,
    )

    # ─── Silence / user-away handling (language-aware) ─────────────────
    silence_prompt_count = {"count": 0}

    @session.on("user_state_changed")
    def _on_user_state(ev):
        try:
            if getattr(ev, "new_state", None) == "away":
                silence_prompt_count["count"] += 1
                if silence_prompt_count["count"] <= 2:
                    lang = tts_instance.current_language if hasattr(tts_instance, 'current_language') else _current_lang["lang"]
                    silence_instruction = SILENCE_PROMPTS.get(lang, SILENCE_PROMPTS["en-IN"])
                    # generate_reply may return a SpeechHandle (sync) or coroutine depending on version
                    result = session.generate_reply(instructions=silence_instruction)
                    if asyncio.iscoroutine(result):
                        asyncio.create_task(result)
                    logger.info("Silence detected — prompting in %s (attempt %d)", lang, silence_prompt_count["count"])
                else:
                    logger.info("Customer unresponsive after 2 prompts — ending call")
                    asyncio.create_task(agent._force_disconnect(delay=2.0))
        except Exception as e:
            logger.debug("user_state handler error: %s", e)

    # ─── Max call duration enforcement (language-aware) ─────────────────
    from app.config.constants import MAX_CALL_DURATION_SECONDS

    async def _enforce_max_duration():
        import asyncio
        await asyncio.sleep(MAX_CALL_DURATION_SECONDS)
        logger.info("Max call duration (%ds) reached — ending", MAX_CALL_DURATION_SECONDS)
        try:
            lang = tts_instance.current_language if hasattr(tts_instance, 'current_language') else _current_lang["lang"]
            wrapup_instruction = WRAPUP_PROMPTS.get(lang, WRAPUP_PROMPTS["en-IN"])
            await session.generate_reply(instructions=wrapup_instruction)
        except Exception:
            pass
        await agent._force_disconnect(delay=5.0)

    import asyncio as _asyncio
    _asyncio.create_task(_enforce_max_duration())

    # ─── Goodbye speech detector (deterministic auto-end) ──────────────
    GOODBYE_PHRASES = {
        # English
        "bye", "goodbye", "take care", "thank you for your time",
        "have a great day", "have a good day",
        # Hindi
        "धन्यवाद", "dhanyawad", "dhanyavaad", "शुक्रिया",
        "अलविदा", "नमस्ते",
        # Kannada
        "ಧನ್ಯವಾದ", "ನಮಸ್ಕಾರ",
        # Telugu
        "ధన్యవాదాలు", "నమస్కారం",
        # Malayalam
        "നന്ദി", "നമസ്കാരം",
        # Tamil
        "நன்றி", "வணக்கம்",
        # Common
        "namaste", "namaskar",
    }
    _goodbye_timer = {"task": None}

    async def _goodbye_auto_end():
        await _asyncio.sleep(10.0)
        if not getattr(agent, "_disconnecting", False):
            logger.info("Goodbye detected but end_call not called — auto-disconnecting")
            await agent._force_disconnect(delay=2.0)

    @session.on("agent_speech_committed")
    def _on_agent_speech(msg):
        try:
            text = ""
            if hasattr(msg, "content"):
                text = str(msg.content).lower()
            elif hasattr(msg, "text"):
                text = str(msg.text).lower()
            elif hasattr(msg, "item") and hasattr(msg.item, "content"):
                for part in (msg.item.content or []):
                    if hasattr(part, "text"):
                        text += str(part.text).lower() + " "

            if not text:
                return

            if any(phrase in text for phrase in GOODBYE_PHRASES):
                if _goodbye_timer["task"] and not _goodbye_timer["task"].done():
                    _goodbye_timer["task"].cancel()
                _goodbye_timer["task"] = _asyncio.create_task(_goodbye_auto_end())
                logger.debug("Goodbye phrase detected in agent speech — 10s auto-end armed")
        except Exception as e:
            logger.debug("Goodbye detector error (non-critical): %s", e)

    # ─── In-call inactivity watchdog ───────────────────────────────────
    from app.config.constants import (
        CONVERSATION_INACTIVITY_TIMEOUT_SECONDS,
        INACTIVITY_WATCHDOG_INTERVAL_SECONDS,
    )

    last_activity = {"ts": time.monotonic()}

    def _mark_activity(*_args, **_kwargs):
        last_activity["ts"] = time.monotonic()

    session.on("user_input_transcribed", _mark_activity)
    session.on("conversation_item_added", _mark_activity)
    session.on("speech_created", _mark_activity)
    session.on("agent_state_changed", _mark_activity)
    session.on("user_state_changed", _mark_activity)

    async def _inactivity_watchdog():
        await _asyncio.sleep(INACTIVITY_WATCHDOG_INTERVAL_SECONDS)
        participant_seen = False

        while True:
            await _asyncio.sleep(INACTIVITY_WATCHDOG_INTERVAL_SECONDS)

            if getattr(agent, "_disconnecting", False):
                return

            try:
                remote_count = len(ctx.room.remote_participants)
            except Exception:
                remote_count = 0

            if remote_count > 0:
                participant_seen = True
            elif participant_seen:
                logger.info("Customer left room %s — ending call", ctx.room.name)
                await agent._force_disconnect(delay=0.0, wait_for_speech=False)
                return

            idle_for = time.monotonic() - last_activity["ts"]
            if idle_for >= CONVERSATION_INACTIVITY_TIMEOUT_SECONDS:
                logger.info(
                    "No conversation for %.0fs on room %s — ending call",
                    idle_for, ctx.room.name,
                )
                await agent._force_disconnect(delay=2.0)
                return

    _asyncio.create_task(_inactivity_watchdog())

    # Register shutdown callback to track call duration and save recording
    @ctx.add_shutdown_callback
    async def on_shutdown():
        duration_seconds = time.time() - call_start_time
        from app.core.data_store import data_store
        data_store.track_call_duration(customer_phone, duration_seconds)

        # Unhook the TTS recorder
        tts_instance._recorder = None

        # Stop the local recorder and save WAV file
        try:
            recording_path = await recorder.stop()
            if recording_path:
                logger.info("Call recording saved: %s", recording_path)
            else:
                logger.warning("No audio captured for recording (room: %s)", ctx.room.name)
        except Exception as e:
            logger.error("Failed to save recording: %s", e)

        # Generate summary + save the conversation transcript
        try:
            turns = transcript.turns
            if turns:
                from app.core.transcript import summarize_transcript
                summary = await summarize_transcript(
                    turns, llm_instance=llm_instance, customer_name=customer_name
                )
                meta = transcript.save(summary=summary)
                if meta:
                    logger.info(
                        "Transcript + summary saved for %s (%d turns)",
                        customer_phone, meta.get("turn_count", 0),
                    )
                try:
                    from app.core.memory import save_conversation
                    save_conversation(
                        phone=customer_phone,
                        summary=summary,
                        outcome="call_completed",
                        preferences={},
                    )
                except Exception as e:
                    logger.debug("Memory save (non-critical): %s", e)
            else:
                logger.info("No transcript turns to save (room: %s)", ctx.room.name)
        except Exception as e:
            logger.error("Failed to save transcript/summary: %s", e)

        logger.info(
            "Call ended for %s. Duration: %.1f seconds",
            customer_phone,
            duration_seconds,
        )


def _resolve_stt_language(language_code: str) -> str:
    """Map language codes to Sarvam STT language codes."""
    mapping = {
        "hi-IN": "hi-IN",
        "en-IN": "en-IN",
        "kn-IN": "kn-IN",
        "te-IN": "te-IN",
        "ml-IN": "ml-IN",
        "ta-IN": "ta-IN",
        "mr-IN": "mr-IN",
        "hi-EN": "hi-IN",
        "unknown": "unknown",
    }
    return mapping.get(language_code, "en-IN")


def _resolve_deepgram_language(language_code: str) -> str:
    """Map language codes to Deepgram language codes."""
    mapping = {
        "hi-IN": "hi",
        "en-IN": "en-IN",
        "kn-IN": "kn",
        "te-IN": "te",
        "ml-IN": "ml",
        "ta-IN": "ta",
        "mr-IN": "mr",
        "hi-EN": "hi",
        "unknown": "en-IN",
    }
    return mapping.get(language_code, "en-IN")
