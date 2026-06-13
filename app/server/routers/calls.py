"""
Calls API — triggers outbound calls via LiveKit SIP.

Creates a LiveKit room with customer metadata, then dispatches
a SIP participant to dial the customer through Plivo SIP trunk.
The agent worker automatically joins the room and handles the conversation.
"""

import asyncio
import json
import logging
import time

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import JSONResponse

from livekit import api

from app.config.settings import settings
from app.config.constants import (
    BATCH_STAGGER_MIN_SECONDS,
    BATCH_STAGGER_MAX_SECONDS,
    BATCH_STAGGER_DEFAULT_SECONDS,
)
from app.core.context import get_runtime_context
from app.core.data_store import data_store
from app.core.scheduler import call_scheduler
from app.server.security import call_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter()


async def _create_livekit_call(name: str, phone: str) -> str:
    """
    Create a LiveKit room and dispatch a SIP call to the customer.

    Flow:
    1. Create a room with customer metadata
    2. Agent worker auto-joins (via LiveKit's agent dispatch)
    3. SIP participant dials the customer's phone via Plivo trunk

    Returns:
        Room name for tracking
    """
    lk_api = api.LiveKitAPI(
        url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )

    # Unique room name per call
    room_name = f"call-{phone.replace('+', '')}-{int(time.time())}"

    # Room metadata carries customer context for the agent
    room_metadata = json.dumps({
        "customer_name": name,
        "customer_phone": phone,
        "language": settings.default_language,
        **get_runtime_context(),
    })

    try:
        # Step 1: Create the room
        await lk_api.room.create_room(
            api.CreateRoomRequest(
                name=room_name,
                metadata=room_metadata,
                empty_timeout=60,  # Close room 60s after last participant leaves
                max_participants=3,  # Agent + Customer + optional monitor
            )
        )
        logger.info("Created room: %s", room_name)

        # Step 2: Dispatch SIP call to customer's phone
        sip_request = api.CreateSIPParticipantRequest(
            sip_trunk_id=settings.sip_outbound_trunk_id,
            sip_call_to=phone,
            room_name=room_name,
            participant_identity=f"customer-{phone}",
            participant_name=name,
        )
        await lk_api.sip.create_sip_participant(sip_request)
        logger.info("SIP call dispatched to %s in room %s", phone, room_name)

    finally:
        await lk_api.aclose()

    return room_name


@router.post("", dependencies=[Depends(call_rate_limit)])
async def trigger_call(payload: dict):
    """Trigger a single outbound call to a customer via SIP (Plivo)."""
    name = payload.get("name")
    phone = payload.get("phone")
    force = bool(payload.get("force", False))

    if not name or not phone:
        return JSONResponse({"error": "name + phone required"}, status_code=400)

    if not settings.sip_outbound_trunk_id:
        return JSONResponse(
            {
                "error": "SIP trunk not configured. To set up phone calling:\n"
                "1. Add PLIVO_AUTH_ID, PLIVO_AUTH_TOKEN, PLIVO_PHONE_NUMBER to .env\n"
                "2. Run: python setup_plivo_trunk.py\n"
                "3. Add the returned SIP_OUTBOUND_TRUNK_ID to .env\n"
                "4. Restart the server\n\n"
                "Or use 'Browser Call' for testing without a phone."
            },
            status_code=400,
        )

    # DND compliance: do not place calls outside the 9 AM - 9 PM IST window.
    # An operator can intentionally override this for a single call by
    # passing {"force": true} (e.g. the customer asked to be called now).
    if not force and not call_scheduler.is_callable_now():
        next_time = call_scheduler.get_next_call_time(phone)
        logger.info(
            "Call to %s blocked by DND window (next callable: %s)", phone, next_time
        )
        return JSONResponse(
            {
                "error": "Outside calling hours (9 AM - 9 PM IST). "
                "Pass force=true to override.",
                "dnd": True,
                "next_call_time": next_time,
            },
            status_code=409,
        )

    try:
        room_name = await _create_livekit_call(name, phone)

        # Update lead status
        data_store.update_lead_status(
            phone, "called", called_at=time.strftime("%Y-%m-%dT%H:%M:%S")
        )

        # Record the dial attempt for retry/analytics tracking.
        # NOTE: the per-lead attempt CAP is intentionally NOT enforced here —
        # a manual single call is a deliberate operator action. The cap is
        # enforced in batch dialing (see _batch_dial).
        call_scheduler.record_attempt(phone, "dialed")

        return {"ok": True, "room_name": room_name, "phone": phone}

    except Exception as e:
        logger.error("Failed to create call for %s: %s", phone, e)
        return JSONResponse({"error": str(e)}, status_code=500)


async def _batch_dial(leads_to_call: list[dict], stagger_sec: int):
    """Background task: dial multiple leads with stagger delay.

    Respects the DND window and the per-lead attempt cap. Leads that are
    not currently callable (outside hours) or have exhausted their retry
    budget are skipped.
    """
    dialed = 0
    for i, lead in enumerate(leads_to_call):
        # Stop dialing entirely if we drift outside the calling window.
        if not call_scheduler.is_callable_now():
            logger.info("Batch dialing paused — outside DND window (9 AM - 9 PM IST)")
            break

        phone = lead["phone"]

        # Honour the per-lead attempt cap for automated dialing.
        if not call_scheduler.can_retry(phone):
            logger.info(
                "Batch: skipping %s — max attempts (%d) reached",
                phone,
                call_scheduler.get_call_attempts(phone),
            )
            continue

        if dialed > 0:
            await asyncio.sleep(stagger_sec)

        try:
            room_name = await _create_livekit_call(lead["name"], phone)
            data_store.update_lead_status(
                phone, "called", called_at=time.strftime("%Y-%m-%dT%H:%M:%S")
            )
            call_scheduler.record_attempt(phone, "dialed")
            dialed += 1
            logger.info("Batch: dialed %s (%s) -> room %s", lead["name"], phone, room_name)

        except Exception as e:
            logger.error("Batch call failed for %s: %s", phone, e)


@router.post("/batch", dependencies=[Depends(call_rate_limit)])
async def call_batch(payload: dict, bg: BackgroundTasks):
    """Batch-dial all pending leads with configurable stagger between calls.

    Skips dialing entirely when outside the DND calling window so a batch
    triggered at night does not place any calls.
    """
    stagger = max(
        BATCH_STAGGER_MIN_SECONDS,
        min(BATCH_STAGGER_MAX_SECONDS, int(payload.get("stagger_sec", BATCH_STAGGER_DEFAULT_SECONDS))),
    )

    # DND compliance: refuse to start a batch outside calling hours.
    if not call_scheduler.is_callable_now():
        return JSONResponse(
            {
                "queued": 0,
                "dnd": True,
                "error": "Outside calling hours (9 AM - 9 PM IST). Batch not started.",
            },
            status_code=409,
        )

    leads = data_store.get_leads()
    pending = [lead for lead in leads if lead["status"] == "pending"]

    # Pre-filter leads that have exhausted their retry budget.
    callable_leads = [lead for lead in pending if call_scheduler.can_retry(lead["phone"])]
    skipped = len(pending) - len(callable_leads)

    if not callable_leads:
        return {"queued": 0, "skipped": skipped, "msg": "No callable pending leads"}

    bg.add_task(_batch_dial, callable_leads, stagger)
    return {"queued": len(callable_leads), "skipped": skipped, "stagger_sec": stagger}


@router.post("/end")
async def end_call(payload: dict):
    """
    Force-end an active call by deleting its LiveKit room.

    Deleting the room disconnects every participant (agent + customer), which
    triggers the agent's normal shutdown path (recording save, outcome logging
    via the agent if it had already run). This is the operator-side equivalent
    of the agent's own end_call tool.

    Request body:
        room_name: The LiveKit room to tear down (as returned by /api/call,
                   /api/call/batch, or /api/webrtc/token).
    """
    room_name = (payload.get("room_name") or "").strip()
    if not room_name:
        return JSONResponse({"error": "room_name required"}, status_code=400)

    lk_api = api.LiveKitAPI(
        url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )
    try:
        await lk_api.room.delete_room(api.DeleteRoomRequest(room=room_name))
        logger.info("Operator ended call — room deleted: %s", room_name)
        return {"ok": True, "room_name": room_name}
    except Exception as e:
        # A non-existent room means the call already ended — that's the desired
        # end state, so treat it as an idempotent success rather than an error.
        if "not_found" in str(e).lower() or "does not exist" in str(e).lower():
            logger.info("end_call: room %s already gone (already ended)", room_name)
            return {"ok": True, "room_name": room_name, "already_ended": True}
        logger.warning("end_call: could not delete room %s: %s", room_name, e)
        return JSONResponse(
            {"ok": False, "room_name": room_name, "error": str(e)},
            status_code=502,
        )
    finally:
        await lk_api.aclose()
