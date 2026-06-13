"""
Inactive-room reaper.

Periodically lists LiveKit rooms and force-deletes any managed room that has
been continuously "inactive" for longer than ROOM_INACTIVITY_TIMEOUT_SECONDS.

"Inactive" is defined conservatively as: no participants, OR no one publishing
audio (num_publishers == 0). A healthy voice call always has at least one
publisher (the agent's TTS track, plus the customer's mic), so live calls are
never flagged. A room must look idle across consecutive sweeps for the full
timeout before it is deleted — the idle timer resets the instant the room
looks active again, so rooms that are still spinning up are not killed.

Only rooms whose names match MANAGED_ROOM_PREFIXES are eligible, so unrelated
rooms in a shared LiveKit project are left untouched.
"""

import logging
import time

from livekit import api

from app.config.settings import settings
from app.config.constants import (
    ROOM_INACTIVITY_TIMEOUT_SECONDS,
    MANAGED_ROOM_PREFIXES,
)

logger = logging.getLogger(__name__)


class InactiveRoomReaper:
    """Tracks per-room idle start times and deletes long-idle rooms."""

    def __init__(self, timeout_seconds: int = ROOM_INACTIVITY_TIMEOUT_SECONDS):
        self._timeout = timeout_seconds
        # room_name -> monotonic timestamp when it first looked idle
        self._idle_since: dict[str, float] = {}

    @staticmethod
    def _is_managed(room_name: str) -> bool:
        return any(room_name.startswith(p) for p in MANAGED_ROOM_PREFIXES)

    @staticmethod
    def _is_idle(room) -> bool:
        """A room is idle when nobody is connected or nobody is publishing."""
        return room.num_participants == 0 or room.num_publishers == 0

    async def sweep(self) -> int:
        """
        Run one sweep. Returns the number of rooms deleted.

        Safe to call repeatedly; all LiveKit errors are caught and logged so a
        transient API failure never crashes the loop.
        """
        lk_api = api.LiveKitAPI(
            url=settings.livekit_url,
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
        )
        deleted = 0
        try:
            resp = await lk_api.room.list_rooms(api.ListRoomsRequest())
            rooms = resp.rooms
            now = time.monotonic()
            seen: set[str] = set()

            for room in rooms:
                name = room.name
                if not self._is_managed(name):
                    continue
                seen.add(name)

                if not self._is_idle(room):
                    # Active again — clear any idle tracking.
                    self._idle_since.pop(name, None)
                    continue

                first_idle = self._idle_since.get(name)
                if first_idle is None:
                    # First time we've seen it idle — start the clock.
                    self._idle_since[name] = now
                    logger.debug("Room %s looks idle — starting idle timer", name)
                    continue

                idle_for = now - first_idle
                if idle_for >= self._timeout:
                    try:
                        await lk_api.room.delete_room(
                            api.DeleteRoomRequest(room=name)
                        )
                        deleted += 1
                        self._idle_since.pop(name, None)
                        logger.info(
                            "Reaped inactive room %s (idle %.0fs, participants=%d, publishers=%d)",
                            name, idle_for, room.num_participants, room.num_publishers,
                        )
                    except Exception as e:
                        logger.warning("Failed to reap room %s: %s", name, e)

            # Forget idle timers for rooms that no longer exist.
            for stale in set(self._idle_since) - seen:
                self._idle_since.pop(stale, None)

        except Exception as e:
            logger.warning("Room reaper sweep error (continuing): %s", e)
        finally:
            await lk_api.aclose()

        return deleted


# Module-level singleton
room_reaper = InactiveRoomReaper()
