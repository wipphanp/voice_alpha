"""
Conversation Transcript + Summary.

Captures the full back-and-forth of a call as a plain-text transcript and,
at the end of the call, produces a concise natural-language summary using the
LLM. Both artifacts are persisted to disk and indexed in a metadata file so
the dashboard / API can list and download them.

Files written (under settings.data_dir / "transcripts"):
    call_<phone>_<timestamp>.txt    — human-readable transcript
    call_<phone>_<timestamp>.json   — structured turns + summary + metadata

A combined index lives at settings.data_dir / "transcripts_meta.json".
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

TRANSCRIPTS_DIR = settings.data_dir / "transcripts"
TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

# Serialize writes to the shared metadata index (two calls may end at once).
_META_LOCK = threading.Lock()

# How a role is labelled in the readable transcript.
_ROLE_LABELS = {
    "user": "Customer",
    "assistant": "Agent",
    "system": "System",
}


class TranscriptRecorder:
    """
    Collects conversation turns during a call and, on stop(), writes a text
    transcript plus a structured JSON record (optionally with an LLM summary).

    Turns are appended live from the AgentSession ``conversation_item_added``
    event so nothing is lost even if the session closes abruptly.
    """

    def __init__(self, room_name: str, customer_phone: str, customer_name: str = ""):
        self._room_name = room_name
        self._customer_phone = customer_phone
        self._customer_name = customer_name
        self._start_time = datetime.now(IST)
        self._turns: list[dict] = []
        self._lock = threading.Lock()
        self._txt_path: Path | None = None
        self._json_path: Path | None = None

    @property
    def txt_path(self) -> Path | None:
        return self._txt_path

    @property
    def turns(self) -> list[dict]:
        with self._lock:
            return list(self._turns)

    def add_turn(self, role: str, text: str) -> None:
        """Record a single conversation turn (agent or customer)."""
        if not text or not text.strip():
            return
        # Skip system / instruction messages — keep only real dialogue.
        if role not in ("user", "assistant"):
            return
        with self._lock:
            self._turns.append({
                "role": role,
                "speaker": _ROLE_LABELS.get(role, role),
                "text": text.strip(),
                "timestamp": datetime.now(IST).isoformat(),
            })

    def has_dialogue(self) -> bool:
        with self._lock:
            return len(self._turns) > 0

    def render_text(self, summary: str | None = None) -> str:
        """Build the human-readable transcript string."""
        with self._lock:
            turns = list(self._turns)

        header = [
            "=" * 60,
            "CALL TRANSCRIPT — Alpha Bot AI",
            "=" * 60,
            f"Customer : {self._customer_name or 'Unknown'} ({self._customer_phone})",
            f"Room     : {self._room_name}",
            f"Date     : {self._start_time.strftime('%Y-%m-%d %H:%M:%S %Z')}",
            f"Turns    : {len(turns)}",
            "=" * 60,
            "",
        ]

        body = []
        for turn in turns:
            ts = turn.get("timestamp", "")
            clock = ts[11:19] if len(ts) >= 19 else ""
            speaker = turn.get("speaker", turn.get("role", ""))
            body.append(f"[{clock}] {speaker}: {turn.get('text', '')}")

        if not body:
            body = ["(No conversation was captured for this call.)"]

        parts = header + body

        if summary:
            parts += [
                "",
                "=" * 60,
                "SUMMARY",
                "=" * 60,
                summary.strip(),
            ]

        return "\n".join(parts) + "\n"

    def save(self, summary: str | None = None) -> dict | None:
        """
        Write the transcript (.txt) and structured record (.json) to disk and
        append to the metadata index. Returns the metadata dict, or None if
        there was no dialogue to save.
        """
        with self._lock:
            turns = list(self._turns)

        if not turns:
            logger.info("No transcript to save for room: %s", self._room_name)
            return None

        ts = self._start_time.strftime("%Y%m%d_%H%M%S")
        phone = self._customer_phone.replace("+", "").replace(" ", "") or "unknown"
        base = f"call_{phone}_{ts}"
        self._txt_path = TRANSCRIPTS_DIR / f"{base}.txt"
        self._json_path = TRANSCRIPTS_DIR / f"{base}.json"

        # Write the human-readable transcript.
        try:
            self._txt_path.write_text(self.render_text(summary), encoding="utf-8")
        except OSError as e:
            logger.error("Failed to write transcript text: %s", e)
            return None

        metadata = {
            "room_name": self._room_name,
            "customer_phone": self._customer_phone,
            "customer_name": self._customer_name,
            "recorded_at": self._start_time.isoformat(),
            "turn_count": len(turns),
            "summary": summary or "",
            "txt_filename": self._txt_path.name,
            "json_filename": self._json_path.name,
        }

        # Write the structured record (turns + summary + metadata).
        try:
            self._json_path.write_text(
                json.dumps({**metadata, "turns": turns}, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as e:
            logger.error("Failed to write transcript JSON: %s", e)

        self._append_metadata(metadata)

        logger.info(
            "Transcript saved: %s (%d turns)", self._txt_path.name, len(turns)
        )
        return metadata

    def _append_metadata(self, metadata: dict) -> None:
        meta_file = settings.data_dir / "transcripts_meta.json"
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


async def summarize_transcript(
    turns: list[dict],
    llm_instance=None,
    customer_name: str = "",
) -> str:
    """
    Generate a concise natural-language summary of the conversation.

    Uses the provided LLM instance (the same one driving the call) via a
    one-shot chat completion. Falls back to a simple heuristic summary if the
    LLM call fails or no instance is available, so a summary is always produced.

    Args:
        turns: list of {"speaker"/"role", "text"} dicts
        llm_instance: a livekit ``llm.LLM`` (e.g. the OpenAI plugin) or None
        customer_name: customer's name for context
    """
    if not turns:
        return "No conversation took place."

    dialogue = "\n".join(
        f"{t.get('speaker', t.get('role', ''))}: {t.get('text', '')}" for t in turns
    )

    if llm_instance is not None:
        try:
            return await _summarize_with_llm(dialogue, llm_instance, customer_name)
        except Exception as e:
            logger.warning("LLM summary failed, using fallback: %s", e)

    return _fallback_summary(turns)


async def _summarize_with_llm(dialogue: str, llm_instance, customer_name: str) -> str:
    """Run a one-shot summarization through the LiveKit LLM plugin."""
    from livekit.agents.llm import ChatContext

    instruction = (
        "You are a real-estate call assistant. Summarize the following phone "
        "conversation between a property broker's AI agent and a customer"
        + (f" named {customer_name}" if customer_name else "")
        + ". Write 3-5 short sentences in English covering: what the customer "
        "wants (budget, location, property type if mentioned), the key points "
        "discussed, and the outcome / next step (e.g. appointment booked, "
        "callback requested, not interested). Be factual and concise.\n\n"
        "Conversation:\n" + dialogue + "\n\nSummary:"
    )

    chat_ctx = ChatContext.empty()
    chat_ctx.add_message(role="user", content=instruction)

    collected: list[str] = []
    async with llm_instance.chat(chat_ctx=chat_ctx) as stream:
        async for chunk in stream:
            delta = getattr(chunk, "delta", None)
            if delta and getattr(delta, "content", None):
                collected.append(delta.content)

    summary = "".join(collected).strip()
    return summary or "Summary unavailable."


def _fallback_summary(turns: list[dict]) -> str:
    """Heuristic summary used when the LLM is unavailable."""
    customer_turns = [t for t in turns if t.get("role") == "user"]
    agent_turns = [t for t in turns if t.get("role") == "assistant"]
    first_customer = customer_turns[0]["text"] if customer_turns else ""
    last_customer = customer_turns[-1]["text"] if customer_turns else ""

    parts = [
        f"Call with {len(turns)} total turns "
        f"({len(customer_turns)} from customer, {len(agent_turns)} from agent).",
    ]
    if first_customer:
        parts.append(f"Customer opened with: \"{first_customer[:120]}\".")
    if last_customer and last_customer != first_customer:
        parts.append(f"Customer last said: \"{last_customer[:120]}\".")
    return " ".join(parts)


def get_transcripts() -> list[dict]:
    """Return all transcript metadata (most recent first)."""
    meta_file = settings.data_dir / "transcripts_meta.json"
    if meta_file.exists():
        try:
            data = json.loads(meta_file.read_text(encoding="utf-8"))
            return list(reversed(data))
        except (json.JSONDecodeError, OSError):
            return []
    return []
