"""
JSON-based data store for leads and bookings.
Thread-safe file operations with atomic writes.
"""

import json
import threading
from pathlib import Path
from typing import Any

from app.config.settings import settings


class DataStore:
    """
    Simple JSON file-based storage with thread-safe read/write.
    Suitable for demo/small-scale usage. Replace with a proper DB
    (PostgreSQL, MongoDB) for production workloads.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._data_dir = settings.data_dir
        self._data_dir.mkdir(parents=True, exist_ok=True)

    @property
    def leads_file(self) -> Path:
        return self._data_dir / "leads.json"

    @property
    def bookings_file(self) -> Path:
        return self._data_dir / "bookings.json"

    def _read(self, path: Path, default: Any = None) -> Any:
        """Read JSON file with lock protection."""
        if default is None:
            default = []
        with self._lock:
            if path.exists():
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    return default
            return default

    def _write(self, path: Path, data: Any) -> None:
        """Atomic write to JSON file."""
        with self._lock:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)

    # ─── Leads ─────────────────────────────────────────────────────────

    def get_leads(self) -> list[dict]:
        return self._read(self.leads_file, [])

    def add_lead(self, name: str, phone: str) -> dict:
        leads = self.get_leads()
        if any(lead["phone"] == phone for lead in leads):
            raise ValueError(f"Phone {phone} already exists")
        lead = {"name": name, "phone": phone, "status": "pending"}
        leads.append(lead)
        self._write(self.leads_file, leads)
        return lead

    def add_leads_bulk(self, new_leads: list[dict]) -> int:
        """Add multiple leads, skip duplicates. Returns count added."""
        leads = self.get_leads()
        existing_phones = {lead["phone"] for lead in leads}
        added = 0
        for entry in new_leads:
            phone = entry.get("phone", "").strip()
            name = entry.get("name", "").strip()
            if phone and phone.startswith("+") and phone not in existing_phones:
                leads.append({"name": name, "phone": phone, "status": "pending"})
                existing_phones.add(phone)
                added += 1
        self._write(self.leads_file, leads)
        return added

    def update_lead_status(self, phone: str, status: str, **extra) -> None:
        leads = self.get_leads()
        for lead in leads:
            if lead["phone"] == phone:
                lead["status"] = status
                lead.update(extra)
                break
        self._write(self.leads_file, leads)

    def clear_leads(self) -> None:
        self._write(self.leads_file, [])

    def delete_lead(self, phone: str) -> None:
        """Delete a single lead by phone."""
        leads = self.get_leads()
        leads = [lead for lead in leads if lead["phone"] != phone]
        self._write(self.leads_file, leads)

    def delete_leads_batch(self, phones: list[str]) -> None:
        """Delete multiple leads by phone numbers."""
        phone_set = set(phones)
        leads = self.get_leads()
        leads = [lead for lead in leads if lead["phone"] not in phone_set]
        self._write(self.leads_file, leads)

    # ─── Bookings ──────────────────────────────────────────────────────

    def get_bookings(self) -> list[dict]:
        return self._read(self.bookings_file, [])

    def add_booking(self, booking: dict) -> None:
        bookings = self.get_bookings()
        bookings.append(booking)
        self._write(self.bookings_file, bookings)

    # ─── Conversations / Memory ────────────────────────────────────────

    @property
    def conversations_file(self) -> Path:
        return self._data_dir / "conversations.json"

    def get_conversations(self) -> dict:
        return self._read(self.conversations_file, {})

    def save_conversation(self, phone: str, entry: dict) -> None:
        conversations = self.get_conversations()
        if phone not in conversations:
            conversations[phone] = []
        conversations[phone].append(entry)
        self._write(self.conversations_file, conversations)

    def get_customer_conversations(self, phone: str) -> list[dict]:
        conversations = self.get_conversations()
        return conversations.get(phone, [])

    # ─── Reminders ─────────────────────────────────────────────────────

    @property
    def reminders_file(self) -> Path:
        return self._data_dir / "reminders.json"

    def get_reminders(self) -> list[dict]:
        return self._read(self.reminders_file, [])

    def save_reminder(self, reminder: dict) -> None:
        reminders = self.get_reminders()
        reminders.append(reminder)
        self._write(self.reminders_file, reminders)

    # ─── WhatsApp Queue ────────────────────────────────────────────────

    @property
    def whatsapp_queue_file(self) -> Path:
        return self._data_dir / "whatsapp_queue.json"

    def get_whatsapp_queue(self) -> list[dict]:
        return self._read(self.whatsapp_queue_file, [])

    def queue_whatsapp_message(self, message: dict) -> None:
        queue = self.get_whatsapp_queue()
        queue.append(message)
        self._write(self.whatsapp_queue_file, queue)

    # ─── Lead Scores ───────────────────────────────────────────────────

    @property
    def lead_scores_file(self) -> Path:
        return self._data_dir / "lead_scores.json"

    def get_lead_scores(self) -> dict:
        return self._read(self.lead_scores_file, {})

    def update_lead_score(self, phone: str, score: str) -> None:
        scores = self.get_lead_scores()
        scores[phone] = score
        self._write(self.lead_scores_file, scores)

    # ─── Call Durations ────────────────────────────────────────────────

    @property
    def call_durations_file(self) -> Path:
        return self._data_dir / "call_durations.json"

    def get_call_durations(self) -> list[dict]:
        return self._read(self.call_durations_file, [])

    def track_call_duration(self, phone: str, duration_seconds: float) -> None:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        IST = ZoneInfo("Asia/Kolkata")
        durations = self.get_call_durations()
        durations.append({
            "phone": phone,
            "duration_seconds": round(duration_seconds, 1),
            "timestamp": datetime.now(IST).isoformat(),
        })
        self._write(self.call_durations_file, durations)


# Module-level singleton
data_store = DataStore()
