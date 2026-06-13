"""
Call Scheduling/Timing Intelligence.

Enforces DND hours, optimal calling windows, and retry logic.
All times are in IST (Asia/Kolkata).
"""

import json
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.config.settings import settings

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")

# DND hours: no calls before 9 AM or after 9 PM IST
DND_START_HOUR = 21  # 9 PM
DND_END_HOUR = 9     # 9 AM

# Optimal calling windows (IST)
OPTIMAL_WINDOWS = [
    (10, 11),  # 10 AM - 11 AM
    (16, 18),  # 4 PM - 6 PM
]

# Retry configuration
MAX_ATTEMPTS = 3
RETRY_DELAYS = [
    timedelta(hours=4),      # After 1st failed attempt — 4 hour gap
    timedelta(hours=4),      # After 2nd failed attempt — 4 hour gap
    timedelta(hours=4),      # After 3rd failed attempt — 4 hour gap
]


class CallScheduler:
    """
    Manages call scheduling with DND enforcement, optimal windows,
    and retry logic with increasing delays.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._data_dir = settings.data_dir
        self._data_dir.mkdir(parents=True, exist_ok=True)

    @property
    def attempts_file(self) -> Path:
        return self._data_dir / "call_attempts.json"

    def _read_attempts(self) -> dict:
        """Read call attempts from JSON file."""
        with self._lock:
            if self.attempts_file.exists():
                try:
                    return json.loads(self.attempts_file.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    return {}
            return {}

    def _write_attempts(self, data: dict) -> None:
        """Atomic write call attempts to JSON file."""
        with self._lock:
            tmp = self.attempts_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.attempts_file)

    def is_callable_now(self) -> bool:
        """
        Check if the current time is appropriate for making calls.
        Returns True if outside DND hours (9 AM - 9 PM IST).
        """
        now = datetime.now(IST)
        return DND_END_HOUR <= now.hour < DND_START_HOUR

    def is_optimal_window(self) -> bool:
        """Check if current time falls within an optimal calling window."""
        now = datetime.now(IST)
        for start, end in OPTIMAL_WINDOWS:
            if start <= now.hour < end:
                return True
        return False

    def get_call_attempts(self, phone: str) -> int:
        """Get number of call attempts for a lead."""
        attempts = self._read_attempts()
        lead_data = attempts.get(phone, {})
        return lead_data.get("attempts", 0)

    def can_retry(self, phone: str) -> bool:
        """Check if a lead can be retried (under max attempts)."""
        return self.get_call_attempts(phone) < MAX_ATTEMPTS

    def record_attempt(self, phone: str, outcome: str) -> None:
        """Record a call attempt for a lead."""
        attempts = self._read_attempts()
        if phone not in attempts:
            attempts[phone] = {"attempts": 0, "history": []}

        attempts[phone]["attempts"] += 1
        attempts[phone]["history"].append({
            "timestamp": datetime.now(IST).isoformat(),
            "outcome": outcome,
        })
        attempts[phone]["last_attempt"] = datetime.now(IST).isoformat()

        self._write_attempts(attempts)

    def get_next_call_time(self, phone: str) -> str | None:
        """
        Returns the optimal next call time for a lead based on retry logic.
        Returns None if max attempts exceeded.
        Returns ISO format datetime string in IST.
        """
        attempts = self._read_attempts()
        lead_data = attempts.get(phone, {})
        attempt_count = lead_data.get("attempts", 0)

        if attempt_count >= MAX_ATTEMPTS:
            return None

        now = datetime.now(IST)

        # Determine delay based on attempt count
        if attempt_count == 0:
            # First call — find next optimal window
            next_time = self._next_optimal_time(now)
        else:
            delay = RETRY_DELAYS[min(attempt_count - 1, len(RETRY_DELAYS) - 1)]
            next_time = now + delay
            # Ensure the retry falls within callable hours
            next_time = self._adjust_to_callable_hours(next_time)

        return next_time.isoformat()

    def reset_attempts(self, phone: str) -> None:
        """Reset call attempts for a lead (e.g., after successful booking)."""
        attempts = self._read_attempts()
        if phone in attempts:
            del attempts[phone]
            self._write_attempts(attempts)

    def get_all_attempts(self) -> dict:
        """Get all call attempt data."""
        return self._read_attempts()

    def _next_optimal_time(self, from_time: datetime) -> datetime:
        """Find the next optimal calling window from the given time."""
        current = from_time

        # Check today's remaining windows
        for start, end in OPTIMAL_WINDOWS:
            if current.hour < start:
                return current.replace(hour=start, minute=0, second=0, microsecond=0)
            elif current.hour < end:
                return current  # We're already in an optimal window

        # No optimal window left today — try tomorrow's first window
        tomorrow = current + timedelta(days=1)
        first_window_start = OPTIMAL_WINDOWS[0][0]
        return tomorrow.replace(hour=first_window_start, minute=0, second=0, microsecond=0)

    def _adjust_to_callable_hours(self, dt: datetime) -> datetime:
        """Adjust a datetime to fall within callable hours (9 AM - 9 PM IST)."""
        if dt.hour >= DND_START_HOUR:
            # Move to next day 9 AM
            next_day = dt + timedelta(days=1)
            return next_day.replace(hour=DND_END_HOUR, minute=0, second=0, microsecond=0)
        elif dt.hour < DND_END_HOUR:
            # Move to 9 AM same day
            return dt.replace(hour=DND_END_HOUR, minute=0, second=0, microsecond=0)
        return dt


# Module-level singleton
call_scheduler = CallScheduler()
