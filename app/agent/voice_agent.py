"""
TradingAssistant — The LiveKit Agent class for Alpha Bot AI Gold & Forex Trading Subscription Agent calls.

This agent handles the full conversation lifecycle:
- Multilingual greeting (Hindi, Kannada, English, Telugu, Malayalam, Tamil)
- Subscription plan explanation with mandatory risk disclaimers
- Demo scheduling and onboarding
- Call outcome logging
- Multi-language support with dynamic switching
- Conversation memory for customer context
- WhatsApp follow-up queuing
- Lead scoring updates
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from livekit.agents import Agent, RunContext, function_tool

from app.core.data_store import data_store
from app.core.memory import save_conversation
from app.core.analytics import compute_lead_score
from app.core.whatsapp import (
    queue_post_call_thankyou,
    queue_subscription_details,
    queue_demo_confirmation,
)
from app.config.constants import VALID_OUTCOMES

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")

LANGUAGE_SWITCH_CONFIGS: dict[str, dict[str, str]] = {
    "hindi": {"display": "Hindi", "stt_code": "hi-IN", "tts_code": "hi-IN"},
    "english": {"display": "English", "stt_code": "en-IN", "tts_code": "en-IN"},
    "kannada": {"display": "Kannada", "stt_code": "kn-IN", "tts_code": "kn-IN"},
    "telugu": {"display": "Telugu", "stt_code": "te-IN", "tts_code": "te-IN"},
    "malayalam": {"display": "Malayalam", "stt_code": "ml-IN", "tts_code": "ml-IN"},
    "tamil": {"display": "Tamil", "stt_code": "ta-IN", "tts_code": "ta-IN"},
    "marathi": {"display": "Marathi", "stt_code": "mr-IN", "tts_code": "mr-IN"},
}


def resolve_language_switch_config(language: str) -> dict[str, str]:
    """Return the runtime config for a language switch request."""
    normalized = (language or "").strip().lower()
    return LANGUAGE_SWITCH_CONFIGS.get(normalized, LANGUAGE_SWITCH_CONFIGS["english"])


class TradingAssistant(Agent):
    """
    LiveKit Agent for Alpha Bot AI Gold & Forex trading subscription calls.

    Handles multi-language conversations (Hindi, Kannada, English, Telugu,
    Malayalam, Tamil) with function tools for scheduling demos, logging
    outcomes, and managing the call lifecycle.
    """

    def __init__(
        self,
        customer_name: str,
        customer_phone: str,
        system_prompt: str,
        stt_instance=None,
        tts_instance=None,
        job_context=None,
    ):
        super().__init__(instructions=system_prompt)
        self.customer_name = customer_name
        self.customer_phone = customer_phone
        self._base_instructions = system_prompt
        self._stt = stt_instance
        self._tts = tts_instance
        self._job_context = job_context
        self._disconnecting = False
        self._active_language_code: str | None = None

    def _compose_language_instructions(self, display_name: str) -> str:
        """Extend the base prompt with the currently active spoken language."""
        return (
            f"{self._base_instructions.rstrip()}\n\n"
            "## Active Language Override\n"
            f"The customer has EXPLICITLY requested {display_name}. "
            f"Continue the ENTIRE conversation in {display_name} from now on.\n"
            "RULES:\n"
            "- Respond DIRECTLY to what the customer says — never ignore their words\n"
            "- Keep domain terms in English (trading, bot, profit, subscription, setup, account, demo, "
            "drawdown, leverage, forex, gold, cent account, lifetime)\n"
            "- Do NOT switch back because the customer uses English words inside sentences\n"
            "- Only switch again if the customer EXPLICITLY asks for a different language\n"
            "- Keep responses SHORT: 1-2 sentences, then STOP and listen"
        )

    def _set_language_runtime(self, *, stt_code: str, tts_code: str) -> None:
        """Update STT/TTS language immediately when the customer requests it."""
        if self._stt is not None:
            if hasattr(self._stt, "set_language"):
                self._stt.set_language(stt_code)
            elif hasattr(self._stt, "update_options"):
                self._stt.update_options(language=stt_code)

        if self._tts is not None and hasattr(self._tts, "set_language"):
            self._tts.set_language(tts_code)

        self._active_language_code = tts_code

    async def apply_language_switch(self, language: str) -> dict:
        """Apply a language switch across runtime components and agent instructions."""
        config = resolve_language_switch_config(language)
        display_name = config["display"]
        stt_code = config["stt_code"]
        tts_code = config["tts_code"]

        self._set_language_runtime(stt_code=stt_code, tts_code=tts_code)

        updated_instructions = self._compose_language_instructions(display_name)
        self._instructions = updated_instructions
        try:
            await self.update_instructions(updated_instructions)
        except Exception as exc:
            logger.debug("Instruction update skipped after language switch: %s", exc)

        logger.info(
            "Language switch completed: %s (STT: %s, TTS: %s) for %s",
            display_name, stt_code, tts_code, self.customer_phone,
        )

        return {
            "status": "switched",
            "language": display_name,
            "stt_language": stt_code,
            "tts_language": tts_code,
            "instruction": (
                f"The customer has switched to {display_name}. "
                f"Continue the ENTIRE conversation in {display_name} from now on. "
                "Keep domain terms in English (trading, bot, profit, subscription, setup, account, demo) "
                "as these are always spoken in English even in regional languages. "
                "Do NOT switch back to any other language just because the customer "
                "uses an English word - that is normal code-switching, not a language request. "
                "Only switch again if they explicitly ask for a different language."
            ),
        }

    @function_tool
    async def schedule_demo(
        self,
        context: RunContext,
        customer_name: str,
        customer_phone: str,
        preferred_time: str,
        preferred_language: str = "English",
        notes: str = "",
    ) -> dict:
        """
        Schedule a demo call with the onboarding team.
        Call this when the customer expresses interest and agrees to a demo/follow-up.

        Args:
            customer_name: Full name of the customer
            customer_phone: Phone number with country code (e.g., +919876543210)
            preferred_time: When the customer wants the demo (e.g., "tomorrow at 3 PM", "Saturday morning")
            preferred_language: Customer's preferred language for the demo
            notes: Additional context (e.g., "experienced trader, interested in Gold")
        """
        booking = {
            "booked_at": datetime.now(IST).isoformat(),
            "type": "demo_scheduled",
            "customer_name": customer_name,
            "customer_phone": customer_phone,
            "preferred_time": preferred_time,
            "preferred_language": preferred_language,
            "notes": notes,
        }

        data_store.add_booking(booking)
        data_store.update_lead_status(customer_phone, "demo_scheduled")
        data_store.update_lead_score(customer_phone, "hot")

        # Queue WhatsApp confirmation
        queue_demo_confirmation(customer_phone, customer_name, preferred_time)

        logger.info(
            "Demo scheduled: %s -> %s (language: %s, WhatsApp queued)",
            customer_name, preferred_time, preferred_language
        )

        return {
            "status": "confirmed",
            "message": (
                f"Demo scheduled for {customer_name} at {preferred_time}. "
                "Confirmation details will be sent via WhatsApp."
            ),
        }

    @function_tool
    async def send_subscription_details(
        self,
        context: RunContext,
        customer_phone: str,
        customer_name: str,
    ) -> dict:
        """
        Send subscription plan details via WhatsApp to the customer.
        Call this when the customer asks for details on WhatsApp or wants written info.

        Args:
            customer_phone: Phone number with country code
            customer_name: Customer's name for personalization
        """
        queue_subscription_details(customer_phone, customer_name)

        logger.info("Subscription details queued for WhatsApp: %s", customer_phone)

        return {
            "status": "queued",
            "message": "Subscription plan details have been queued for WhatsApp delivery.",
        }

    @function_tool
    async def log_call_outcome(
        self,
        context: RunContext,
        customer_phone: str,
        outcome: str,
        notes: str = "",
    ) -> dict:
        """
        Log the final call outcome. You MUST invoke this before saying goodbye.
        This must be the last tool call in every conversation.

        Args:
            customer_phone: Phone number with country code
            outcome: One of: interested_demo_scheduled, callback_requested,
                     not_interested_now, dnc_requested, customer_busy_reschedule
            notes: Brief summary of the conversation
        """
        if outcome not in VALID_OUTCOMES:
            return {
                "status": "error",
                "message": f"Invalid outcome. Must be one of: {VALID_OUTCOMES}",
            }

        entry = {
            "booked_at": datetime.now(IST).isoformat(),
            "customer_phone": customer_phone,
            "outcome": outcome,
            "notes": notes,
        }

        data_store.add_booking(entry)
        data_store.update_lead_status(customer_phone, "completed", outcome=outcome)

        # Update lead score based on outcome
        score = compute_lead_score(outcome)
        data_store.update_lead_score(customer_phone, score)

        # Save conversation summary to memory
        save_conversation(
            phone=customer_phone,
            summary=notes or f"Call ended with outcome: {outcome}",
            outcome=outcome,
            preferences={},
        )

        # Queue WhatsApp follow-up (post-call thank you)
        if outcome != "dnc_requested":
            queue_post_call_thankyou(customer_phone, self.customer_name)

        logger.info(
            "Call outcome logged: %s -> %s (score: %s, WhatsApp queued)",
            customer_phone, outcome, score,
        )

        # Auto-schedule disconnect
        import asyncio
        if outcome == "dnc_requested":
            asyncio.create_task(self._force_disconnect(delay=4.0))
            logger.info("DNC detected — fast call termination for %s", customer_phone)
        else:
            asyncio.create_task(self._force_disconnect(delay=8.0))
            logger.info("Call outcome logged — auto-disconnect scheduled for %s", customer_phone)

        return {"status": "logged", "outcome": outcome, "lead_score": score}

    async def _force_disconnect(self, delay: float = 4.0, wait_for_speech: bool = True) -> None:
        """Force-close the call: wait for goodbye to finish, then tear down."""
        import asyncio

        if self._disconnecting:
            return
        self._disconnecting = True

        session = self.session

        if wait_for_speech:
            try:
                await asyncio.wait_for(
                    self._wait_for_speech_done(session), timeout=20.0
                )
            except asyncio.TimeoutError:
                logger.debug("Goodbye playout wait timed out — proceeding to disconnect")
            except Exception as e:
                logger.debug("Speech-wait error (non-critical): %s", e)

            await asyncio.sleep(0.5)

        try:
            if session is not None:
                await session.aclose()
                logger.info("Agent session closed for %s", self.customer_phone)
        except Exception as e:
            logger.debug("session.aclose() error (non-critical): %s", e)

        room_name = None
        try:
            if self._job_context is not None and self._job_context.room is not None:
                room_name = self._job_context.room.name
        except Exception:
            room_name = None

        try:
            if self._job_context is not None:
                await self._job_context.delete_room()
                logger.info("Room deleted via JobContext: %s", room_name)
            else:
                await self._delete_room_via_api(session)
        except Exception as e:
            logger.warning("delete_room failed, trying API fallback: %s", e)
            try:
                await self._delete_room_via_api(session)
            except Exception as e2:
                logger.debug("API room-delete fallback failed: %s", e2)

        try:
            if self._job_context is not None:
                self._job_context.shutdown(reason="call ended")
        except Exception as e:
            logger.debug("JobContext.shutdown error (non-critical): %s", e)

    async def _wait_for_speech_done(self, session) -> None:
        """Block until the agent's current speech has finished playing out."""
        import asyncio

        if session is None:
            return
        while True:
            speech = getattr(session, "current_speech", None)
            if speech is None:
                await asyncio.sleep(0.2)
                if getattr(session, "current_speech", None) is None:
                    return
                continue
            try:
                await speech.wait_for_playout()
            except Exception:
                return
            await asyncio.sleep(0.1)

    async def _delete_room_via_api(self, session) -> None:
        """Fallback room teardown using a fresh LiveKit API client."""
        from livekit import api
        from app.config.settings import settings

        room = None
        room_io = getattr(session, "_room_io", None) if session else None
        if room_io is not None:
            room = getattr(room_io, "room", None)
        if room is None or not getattr(room, "name", None):
            return

        lk_api = api.LiveKitAPI(
            url=settings.livekit_url,
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
        )
        try:
            await lk_api.room.delete_room(api.DeleteRoomRequest(room=room.name))
            logger.info("Force disconnect: room deleted %s", room.name)
        finally:
            await lk_api.aclose()

    @function_tool
    async def switch_language(
        self,
        context: RunContext,
        language: str,
    ) -> dict:
        """
        Switch the conversation language ONLY when the customer EXPLICITLY and
        DIRECTLY asks you to speak in a different language.

        VALID triggers (customer must say something like):
        - "Hindi mein baat karo" / "Speak in Hindi"
        - "Switch to English please"
        - "Tamil la pesungal" / "Talk in Tamil"
        - "Kannada nalli maatadi"

        NEVER call this tool when:
        - Customer uses English words inside a regional language sentence (normal
          code-switching like "trading account open madidini" in Kannada)
        - Customer uses domain terms like "profit", "bot", "subscription", "setup",
          "account", "demo" in English — these are always English across all languages
        - Customer says a single English word or short phrase while otherwise speaking
          their chosen language
        - Customer simply RESPONDS in a different language without explicitly asking
          you to switch — continue in your current language and reply naturally
        - You THINK the customer might prefer a different language — do NOT assume

        ONLY switch when the customer gives a CLEAR, EXPLICIT instruction to change
        the language of the conversation.

        Args:
            language: Target language - one of: hindi, english, kannada, telugu, malayalam, tamil, marathi
        """
        return await self.apply_language_switch(language)

    @function_tool
    async def request_callback(
        self,
        context: RunContext,
        callback_time: str,
        notes: str = "",
    ) -> dict:
        """
        Capture a callback request when the customer is busy or wants to be called later.

        Args:
            callback_time: When to call back (e.g., "tomorrow at 3 PM", "evening", "next week")
            notes: Why they want a callback / any context
        """
        entry = {
            "booked_at": datetime.now(IST).isoformat(),
            "customer_phone": self.customer_phone,
            "customer_name": self.customer_name,
            "callback_time": callback_time,
            "notes": notes,
            "type": "callback_scheduled",
        }
        data_store.add_booking(entry)
        data_store.update_lead_score(self.customer_phone, "warm")

        logger.info(
            "Callback requested by %s at: %s", self.customer_phone, callback_time,
        )

        return {
            "status": "scheduled",
            "callback_time": callback_time,
            "message": f"Callback noted for {callback_time}.",
        }

    @function_tool
    async def mark_wrong_number(
        self,
        context: RunContext,
        notes: str = "",
    ) -> dict:
        """
        Call this when the person says it's a wrong number or they are NOT
        the customer you're looking for.

        Args:
            notes: Any context (e.g., "number reassigned to different person")
        """
        entry = {
            "booked_at": datetime.now(IST).isoformat(),
            "customer_phone": self.customer_phone,
            "outcome": "wrong_number",
            "notes": notes or "Wrong number / person not found",
            "type": "wrong_number",
        }
        data_store.add_booking(entry)
        data_store.update_lead_status(self.customer_phone, "wrong_number")
        data_store.update_lead_score(self.customer_phone, "dead")

        logger.info("Wrong number flagged for %s — ending call", self.customer_phone)

        import asyncio
        asyncio.create_task(self._force_disconnect(delay=3.0))

        return {
            "status": "wrong_number_logged",
            "message": "Wrong number logged. Call ending.",
        }

    @function_tool
    async def handle_dispute(
        self,
        context: RunContext,
        dispute_type: str,
        notes: str = "",
    ) -> dict:
        """
        Call this IMMEDIATELY when the customer raises a privacy complaint,
        legal threat, or says they will file a police complaint / legal notice.

        Args:
            dispute_type: Type (e.g., "privacy_complaint", "legal_threat", "police_threat")
            notes: Brief context of what the customer said
        """
        entry = {
            "booked_at": datetime.now(IST).isoformat(),
            "customer_phone": self.customer_phone,
            "outcome": "dnc_requested",
            "notes": f"DISPUTE/{dispute_type}: {notes}",
            "type": "dispute",
        }
        data_store.add_booking(entry)
        data_store.update_lead_status(self.customer_phone, "completed", outcome="dnc_requested")
        data_store.update_lead_score(self.customer_phone, "dead")

        save_conversation(
            phone=self.customer_phone,
            summary=f"Customer raised {dispute_type}. Number marked DO NOT CALL.",
            outcome="dnc_requested",
            preferences={"do_not_call": "true", "dispute": dispute_type},
        )

        logger.warning(
            "DISPUTE (%s) from %s — number marked DNC, force-ending call",
            dispute_type, self.customer_phone,
        )

        import asyncio
        asyncio.create_task(self._force_disconnect(delay=5.0))

        return {
            "status": "dispute_logged",
            "instruction": (
                "Say ONE short apology and goodbye ONLY, then STOP completely: "
                "'I sincerely apologize for the inconvenience. Your number has been removed "
                "from our list. You will not receive any further calls. Thank you.' "
                "Do NOT say anything after this. The call will disconnect."
            ),
        }

    @function_tool
    async def end_call(
        self,
        context: RunContext,
        reason: str,
    ) -> dict:
        """
        Gracefully end and disconnect the call. Call this after saying your final goodbye.

        Args:
            reason: Brief reason for ending (e.g., "demo scheduled", "customer said bye", "not interested")
        """
        logger.info("Call ending for %s: %s", self.customer_phone, reason)

        import asyncio
        asyncio.create_task(self._force_disconnect(delay=4.0))

        return {
            "status": "ending",
            "message": f"Call disconnecting: {reason}",
        }

    @function_tool
    async def save_conversation_summary(
        self,
        context: RunContext,
        summary: str,
        outcome: str,
        trading_experience: str = "",
        interest_level: str = "",
        objections: str = "",
        preferred_capital: str = "",
        notes: str = "",
    ) -> dict:
        """
        Save a summary of this conversation for future reference.
        Call this BEFORE log_call_outcome to capture key details about the customer.

        Args:
            summary: Brief 1-2 sentence summary of what was discussed
            outcome: Call outcome (interested_demo_scheduled, callback_requested, not_interested_now, etc.)
            trading_experience: Customer's trading experience level (novice, intermediate, experienced)
            interest_level: How interested they seemed (high, medium, low)
            objections: Any objections raised (e.g., "concerned about risk", "price too high")
            preferred_capital: How much they want to invest (e.g., "$500", "$1000")
            notes: Any other important details
        """
        preferences = {}
        if trading_experience:
            preferences["trading_experience"] = trading_experience
        if interest_level:
            preferences["interest_level"] = interest_level
        if objections:
            preferences["objections"] = objections
        if preferred_capital:
            preferences["preferred_capital"] = preferred_capital
        if notes:
            preferences["notes"] = notes

        save_conversation(
            phone=self.customer_phone,
            summary=summary,
            outcome=outcome,
            preferences=preferences,
        )

        logger.info(
            "Conversation summary saved for %s: %s",
            self.customer_phone, summary[:80],
        )

        return {
            "status": "saved",
            "message": "Conversation summary saved for future reference.",
        }
