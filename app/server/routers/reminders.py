"""
Reminders API router.

Provides endpoints for checking and managing appointment reminders.
"""

from fastapi import APIRouter

from app.core.reminders import reminder_manager
from app.core.whatsapp import send_appointment_reminder

router = APIRouter()


@router.get("/")
async def get_reminders():
    """
    Get all reminders — both sent and pending.
    Pending reminders are appointments that haven't been reminded yet.
    """
    return reminder_manager.get_all_reminders()


@router.get("/pending")
async def get_pending_reminders():
    """Get appointments that need reminders sent."""
    return reminder_manager.get_pending_reminders()


@router.get("/upcoming")
async def get_upcoming_appointments():
    """Get all upcoming appointments (within 24 hours)."""
    return reminder_manager.get_upcoming_appointments()


@router.post("/send/{phone}")
async def send_reminder(phone: str, slot: str = ""):
    """
    Send a reminder for a specific appointment.

    Args:
        phone: Customer phone number (URL path parameter)
        slot: Appointment slot (query parameter)
    """
    # Find the appointment
    pending = reminder_manager.get_pending_reminders()
    target = None

    for appt in pending:
        if appt["customer_phone"] == phone:
            if not slot or appt["slot_chosen"] == slot:
                target = appt
                break

    if not target:
        return {"status": "error", "message": "No pending reminder found for this phone/slot"}

    # Generate and send reminder
    message = reminder_manager.generate_reminder_message(
        target["customer_name"],
        target["slot_chosen"],
    )
    result = send_appointment_reminder(
        phone,
        target["customer_name"],
        target["slot_chosen"],
    )

    # Mark as sent
    reminder_manager.mark_reminder_sent(phone, target["slot_chosen"])

    return {
        "status": "sent",
        "reminder": target,
        "whatsapp_result": result,
    }
