"""
Customer Context Memory.

Stores conversation summaries per customer phone number.
Enables the agent to recall past interactions, preferences,
and behavioral patterns for personalized follow-ups.
"""

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.config.settings import settings

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")


class ConversationMemory:
    """
    Persistent memory for customer conversations.
    Stores summaries, outcomes, and extracted preferences.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._data_dir = settings.data_dir
        self._data_dir.mkdir(parents=True, exist_ok=True)

    @property
    def conversations_file(self) -> Path:
        return self._data_dir / "conversations.json"

    def _read_conversations(self) -> dict:
        """Read conversations from JSON file. Returns {phone: [entries]}."""
        with self._lock:
            if self.conversations_file.exists():
                try:
                    return json.loads(self.conversations_file.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    return {}
            return {}

    def _write_conversations(self, data: dict) -> None:
        """Atomic write conversations to JSON file."""
        with self._lock:
            tmp = self.conversations_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.conversations_file)

    def save_conversation(
        self,
        phone: str,
        summary: str,
        outcome: str,
        preferences: dict | None = None,
    ) -> None:
        """
        Save a conversation summary for a customer.

        Args:
            phone: Customer phone number
            summary: Brief summary of the conversation
            outcome: Call outcome (e.g., appointment_booked, callback_requested)
            preferences: Extracted preferences (budget, location, property type, etc.)
        """
        conversations = self._read_conversations()

        if phone not in conversations:
            conversations[phone] = []

        entry = {
            "timestamp": datetime.now(IST).isoformat(),
            "summary": summary,
            "outcome": outcome,
            "preferences": preferences or {},
        }

        conversations[phone].append(entry)
        self._write_conversations(conversations)

    def get_customer_history(self, phone: str) -> str | None:
        """
        Get formatted conversation history for a customer.
        Returns a human-readable string for inclusion in the system prompt.
        Returns None if no history exists.

        Args:
            phone: Customer phone number
        """
        conversations = self._read_conversations()
        entries = conversations.get(phone, [])

        if not entries:
            return None

        # Format history for the agent's context
        history_parts = []
        for i, entry in enumerate(entries[-5:], 1):  # Last 5 conversations
            ts = entry.get("timestamp", "")
            summary = entry.get("summary", "")
            outcome = entry.get("outcome", "")
            prefs = entry.get("preferences", {})

            part = f"**Call {i}** ({ts[:10]}): {summary}\n  Outcome: {outcome}"
            if prefs:
                pref_str = ", ".join(f"{k}: {v}" for k, v in prefs.items() if v)
                if pref_str:
                    part += f"\n  Preferences: {pref_str}"
            history_parts.append(part)

        return "\n".join(history_parts)

    def get_customer_preferences(self, phone: str) -> dict:
        """
        Get aggregated customer preferences from past conversations.
        Merges preferences from all past calls, latest values take priority.

        Args:
            phone: Customer phone number

        Returns:
            dict with extracted preferences (budget, location, property_type, etc.)
        """
        conversations = self._read_conversations()
        entries = conversations.get(phone, [])

        if not entries:
            return {}

        # Merge all preferences, latest overrides earlier
        merged = {}
        for entry in entries:
            prefs = entry.get("preferences", {})
            for key, value in prefs.items():
                if value:  # Only override with non-empty values
                    merged[key] = value

        return merged

    def get_all_customers(self) -> dict:
        """Get all customer conversation data."""
        return self._read_conversations()


# Module-level singleton
conversation_memory = ConversationMemory()


# ─── Convenience functions (used by agent and API) ─────────────────────────

def save_conversation(
    phone: str,
    summary: str,
    outcome: str,
    preferences: dict | None = None,
) -> None:
    """Save a conversation summary for a customer."""
    conversation_memory.save_conversation(phone, summary, outcome, preferences)


def get_customer_history(phone: str) -> str | None:
    """Get formatted customer history for system prompt injection."""
    return conversation_memory.get_customer_history(phone)


def get_customer_preferences(phone: str) -> dict:
    """Get aggregated customer preferences."""
    return conversation_memory.get_customer_preferences(phone)
