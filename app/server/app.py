"""
FastAPI application factory.
Creates the app with all routers mounted.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from .routers import (
    leads_router,
    calls_router,
    bookings_router,
    context_router,
    dashboard_router,
    webrtc_router,
    reminders_router,
    analytics_router,
    recordings_router,
    transcripts_router,
)
from .security import require_auth, get_cors_origins, auth_enabled

logger = logging.getLogger(__name__)


async def _reminder_loop():
    """Periodically send due demo call reminders (runs in the server process)."""
    from app.config.constants import REMINDER_CHECK_INTERVAL_SECONDS
    from app.core.reminders import reminder_manager

    logger.info(
        "Reminder loop started (every %ds)", REMINDER_CHECK_INTERVAL_SECONDS
    )
    while True:
        try:
            await asyncio.sleep(REMINDER_CHECK_INTERVAL_SECONDS)
            # send_due_reminders is sync + file-bound; run off the event loop.
            sent = await asyncio.to_thread(reminder_manager.send_due_reminders)
            if sent:
                logger.info("Reminder loop: sent %d reminder(s)", sent)
        except asyncio.CancelledError:
            logger.info("Reminder loop stopped")
            break
        except Exception as e:
            logger.error("Reminder loop error (continuing): %s", e)


async def _room_reaper_loop():
    """Periodically force-delete LiveKit rooms that have been inactive too long."""
    from app.config.constants import (
        ROOM_REAPER_INTERVAL_SECONDS,
        ROOM_INACTIVITY_TIMEOUT_SECONDS,
    )
    from app.core.room_monitor import room_reaper

    logger.info(
        "Room reaper started (every %ds, inactivity timeout %ds)",
        ROOM_REAPER_INTERVAL_SECONDS,
        ROOM_INACTIVITY_TIMEOUT_SECONDS,
    )
    while True:
        try:
            await asyncio.sleep(ROOM_REAPER_INTERVAL_SECONDS)
            reaped = await room_reaper.sweep()
            if reaped:
                logger.info("Room reaper: deleted %d inactive room(s)", reaped)
        except asyncio.CancelledError:
            logger.info("Room reaper stopped")
            break
        except Exception as e:
            logger.error("Room reaper error (continuing): %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start/stop background tasks alongside the server."""
    tasks = [
        asyncio.create_task(_reminder_loop()),
        asyncio.create_task(_room_reaper_loop()),
    ]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Alpha Bot AI Voice Agent",
        description="LiveKit + Sarvam AI powered multilingual Gold & Forex trading subscription voice agent",
        version="2.0.0",
        lifespan=lifespan,
    )

    # ─── Security posture warning ──────────────────────────────────────
    if not auth_enabled():
        logger.warning(
            "SECURITY: API auth is DISABLED (no API_AUTH_TOKEN set). The "
            "dashboard and all /api routes — including outbound calling and "
            "lead data — are open to anyone who can reach this server. Set "
            "API_AUTH_TOKEN in .env before exposing it beyond localhost."
        )

    # CORS — locked to explicit origins (defaults to localhost on the
    # configured port). We use header tokens, not cookies, so credentials
    # are not allowed.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_cors_origins(),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Auth dependency applied to all /api routers below. When no token is
    # configured, require_auth is a no-op (current open behavior preserved).
    auth = [Depends(require_auth)]

    # Mount routers
    app.include_router(dashboard_router, tags=["Dashboard"])
    app.include_router(context_router, prefix="/api", tags=["Context"], dependencies=auth)
    app.include_router(leads_router, prefix="/api/leads", tags=["Leads"], dependencies=auth)
    app.include_router(calls_router, prefix="/api/call", tags=["Calls"], dependencies=auth)
    app.include_router(bookings_router, prefix="/api/bookings", tags=["Bookings"], dependencies=auth)
    app.include_router(webrtc_router, prefix="/api/webrtc", tags=["WebRTC"], dependencies=auth)
    app.include_router(analytics_router, prefix="/api/analytics", tags=["Analytics"], dependencies=auth)
    app.include_router(reminders_router, prefix="/api/reminders", tags=["Reminders"], dependencies=auth)
    app.include_router(recordings_router, prefix="/api/recordings", tags=["Recordings"], dependencies=auth)
    app.include_router(transcripts_router, prefix="/api/transcripts", tags=["Transcripts"], dependencies=auth)

    @app.get("/api/status")
    async def get_status():
        """Return system status including SIP trunk availability.

        Intentionally public (no auth) — a lightweight health/config probe
        the dashboard uses; exposes no secrets.
        """
        from app.config.settings import settings
        return {
            "sip_configured": bool(settings.sip_outbound_trunk_id),
            "livekit_url": settings.livekit_url,
            "tts_voice": settings.sarvam_tts_speaker,
            "use_sarvam_llm": settings.use_sarvam_llm,
            "auth_required": auth_enabled(),
        }

    return app
