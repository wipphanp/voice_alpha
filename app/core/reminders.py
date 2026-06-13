"""
Appointment Reminder Flow.

Checks upcoming appointments and generates reminder messages for WhatsApp.
Tracks reminder status (sent/pending).
"""

import json
import logging
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.config.settings import settings
from app.core.data_store import data_store

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")

# Reminder window: appointments within the next 24 hours
REMINDER_WINDOW_HOURS = 24

# Month name → number lookup for slot parsing
_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


def parse_appointment_slot(slot: str, now: datetime | None = None) -> datetime | None:
    """
    Best-effort parse of a free-text appointment slot into an IST datetime.

    Handles the English format the agent typically produces, e.g.
    "Monday June 12 at 1 PM", "Saturday June 6 at 5 PM", "June 8 at 11:30 AM".

    Returns None for slots that cannot be confidently parsed (e.g. Hinglish
    free-text like "kal subah"). Callers MUST treat None as "unknown time"
    and never auto-send a reminder for it — this avoids mis-timed messages.
    """
    if not slot:
        return None

    now = now or datetime.now(IST)
    text = slot.lower()

    # Month + day (e.g. "june 12")
    month_match = re.search(
        r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+(\d{1,2})",
        text,
    )
    if not month_match:
        return None

    month = _MONTHS.get(month_match.group(1))
    day = int(month_match.group(2))
    if not month or not (1 <= day <= 31):
        return None

    # Time (e.g. "1 pm", "11 am", "5:30 pm"). Default to 11:00 (the app's
    # standard slot hour) when no explicit time is present.
    hour, minute = 11, 0
    time_match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", text)
    if time_match:
        hour = int(time_match.group(1)) % 12
        minute = int(time_match.group(2)) if time_match.group(2) else 0
        if time_match.group(3) == "pm":
            hour += 12

    year = now.year
    try:
        dt = datetime(year, month, day, hour, minute, tzinfo=IST)
    except ValueError:
        return None

    # Year-boundary handling: a date far in the past likely means next year
    # (e.g. booking a "January" slot in December).
    if dt < now - timedelta(days=60):
        try:
            dt = dt.replace(year=year + 1)
        except ValueError:
            return None

    return dt


class ReminderManager:
    """
    Manages appointment reminders — checks upcoming bookings and
    generates WhatsApp reminder messages.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._data_dir = settings.data_dir
        self._data_dir.mkdir(parents=True, exist_ok=True)

    @property
    def reminders_file(self) -> Path:
        return self._data_dir / "reminders.json"

    def _read_reminders(self) -> list[dict]:
        """Read reminder status from JSON file."""
        with self._lock:
            if self.reminders_file.exists():
                try:
                    return json.loads(self.reminders_file.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    return []
            return []

    def _write_reminders(self, data: list[dict]) -> None:
        """Atomic write reminders to JSON file."""
        with self._lock:
            tmp = self.reminders_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.reminders_file)

    def get_upcoming_appointments(self) -> list[dict]:
        """
        Get appointment bookings, enriched with parsed timing info.

        Each entry gains additive fields:
          - appointment_time: ISO datetime string, or "" if unparseable
          - hours_until: float hours from now, or None if unparseable
          - parse_ok: bool — whether the slot was successfully parsed

        NOTE: this returns ALL appointment bookings (not just future ones) so
        existing callers keep working; use get_due_reminders() for the
        time-windowed set actually eligible for an automatic reminder.
        """
        bookings = data_store.get_bookings()
        now = datetime.now(IST)

        upcoming = []
        for booking in bookings:
            if booking.get("type") != "appointment_booked":
                continue

            slot = booking.get("slot_chosen", "")
            appt_dt = parse_appointment_slot(slot, now)

            entry = {
                "customer_name": booking.get("customer_name", "Customer"),
                "customer_phone": booking.get("customer_phone", ""),
                "slot_chosen": slot,
                "booked_at": booking.get("booked_at", ""),
                "appointment_time": appt_dt.isoformat() if appt_dt else "",
                "hours_until": (
                    round((appt_dt - now).total_seconds() / 3600, 1) if appt_dt else None
                ),
                "parse_ok": appt_dt is not None,
            }
            upcoming.append(entry)

        return upcoming

    def get_due_reminders(self) -> list[dict]:
        """
        Appointments eligible for an automatic reminder right now:
          - the slot was parseable,
          - it is in the future,
          - it falls within the next REMINDER_WINDOW_HOURS,
          - and a reminder has not already been sent for it.

        Unparseable slots are intentionally excluded so we never send a
        mis-timed reminder.
        """
        now = datetime.now(IST)
        sent_reminders = self._read_reminders()
        sent_keys = {
            f"{r.get('customer_phone', '')}_{r.get('slot_chosen', '')}"
            for r in sent_reminders
        }

        due = []
        for appt in self.get_upcoming_appointments():
            if not appt["parse_ok"]:
                continue
            hours_until = appt["hours_until"]
            if hours_until is None or hours_until < 0:
                continue  # past appointment
            if hours_until > REMINDER_WINDOW_HOURS:
                continue  # too far out
            key = f"{appt['customer_phone']}_{appt['slot_chosen']}"
            if key in sent_keys:
                continue  # already reminded
            due.append(appt)

        return due

    def send_due_reminders(self) -> int:
        """
        Send reminders for all due appointments via the WhatsApp layer and
        mark each as sent. Idempotent — already-sent reminders are skipped.

        Returns the number of reminders sent.
        """
        # Imported here to avoid a circular import at module load time.
        from app.core.whatsapp import send_appointment_reminder

        due = self.get_due_reminders()
        sent_count = 0

        for appt in due:
            phone = appt["customer_phone"]
            if not phone:
                continue
            try:
                send_appointment_reminder(
                    phone, appt["customer_name"], appt["slot_chosen"]
                )
                self.mark_reminder_sent(phone, appt["slot_chosen"])
                sent_count += 1
                logger.info(
                    "Reminder sent to %s for %s (in %.1fh)",
                    phone, appt["slot_chosen"], appt["hours_until"],
                )
            except Exception as e:
                logger.error("Failed to send reminder to %s: %s", phone, e)

        if sent_count:
            logger.info("send_due_reminders: %d reminder(s) sent", sent_count)
        return sent_count

    def get_pending_reminders(self) -> list[dict]:
        """
        Get appointments needing reminders (not yet sent).
        Returns list of appointments with reminder status.
        """
        upcoming = self.get_upcoming_appointments()
        sent_reminders = self._read_reminders()
        sent_keys = {
            f"{r['customer_phone']}_{r['slot_chosen']}" for r in sent_reminders
        }

        pending = []
        for appt in upcoming:
            key = f"{appt['customer_phone']}_{appt['slot_chosen']}"
            if key not in sent_keys:
                appt["reminder_status"] = "pending"
                pending.append(appt)

        return pending

    def generate_reminder_message(self, customer_name: str, slot: str) -> str:
        """Generate a WhatsApp reminder message for a demo call."""
        from app.config.constants import COMPANY_NAME, COMPANY_PHONE

        message = (
            f"📊 Demo Call Reminder\n\n"
            f"Hello {customer_name}!\n\n"
            f"This is a reminder for your scheduled demo call:\n"
            f"📅 {slot}\n\n"
            f"Our team will walk you through the Alpha Bot AI trading system.\n"
            f"📞 {COMPANY_PHONE}\n\n"
            f"Looking forward to speaking with you!\n"
            f"— Team {COMPANY_NAME}\n\n"
            f"If you need to reschedule, please reply or call us back."
        )
        return message

    def mark_reminder_sent(self, customer_phone: str, slot: str) -> None:
        """Mark a reminder as sent."""
        reminders = self._read_reminders()
        reminders.append({
            "customer_phone": customer_phone,
            "slot_chosen": slot,
            "sent_at": datetime.now(IST).isoformat(),
            "status": "sent",
        })
        self._write_reminders(reminders)

    def get_all_reminders(self) -> dict:
        """Get all reminder records (sent and pending)."""
        sent = self._read_reminders()
        pending = self.get_pending_reminders()
        return {
            "sent": sent,
            "pending": pending,
        }


# Module-level singleton
reminder_manager = ReminderManager()
