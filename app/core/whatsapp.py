"""
WhatsApp Follow-up Integration (stub with Twilio/Plivo).

Provides functions for sending WhatsApp messages — currently logs messages
as stubs. Actual integration with Twilio or Plivo can be added later.

Also provides message queuing (stored in data/whatsapp_queue.json)
for async/batch processing.
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config.constants import BRAND_NAME, PRODUCT_NAME, COMPANY_PHONE, COMPANY_WEBSITE

# Aliases for message templates
COMPANY_NAME = BRAND_NAME

from app.config.settings import settings

IST = ZoneInfo("Asia/Kolkata")


def send_whatsapp_message(phone: str, message: str) -> dict:
    """
    Send a WhatsApp message to a phone number.

    Currently a stub that logs the message. Replace with actual
    Twilio/Plivo API call when ready.

    Args:
        phone: Phone number with country code (e.g., +919876543210)
        message: Message text to send

    Returns:
        dict with status and details
    """
    api_key = settings.whatsapp_api_key
    from_number = settings.whatsapp_phone_number

    if not api_key:
        logger.warning(
            "[WhatsApp STUB] No API key configured. Message NOT sent to %s: %s",
            phone,
            message[:100],
        )
        return {
            "status": "stub",
            "message": "WhatsApp API key not configured. Message logged only.",
            "phone": phone,
            "content": message,
            "timestamp": datetime.now(IST).isoformat(),
        }

    logger.info(
        "[WhatsApp] Sending message to %s from %s: %s",
        phone,
        from_number,
        message[:100],
    )

    return {
        "status": "sent",
        "phone": phone,
        "from": from_number,
        "content": message,
        "timestamp": datetime.now(IST).isoformat(),
    }


def queue_whatsapp_message(phone: str, message: str, message_type: str = "general") -> dict:
    """
    Queue a WhatsApp message for later sending.

    Args:
        phone: Customer phone number with country code
        message: Message text content
        message_type: Type of message (post_call_thanks, subscription_details,
                      demo_confirmation, follow_up)

    Returns:
        dict with queue status
    """
    from app.core.data_store import data_store

    entry = {
        "phone": phone,
        "message": message,
        "message_type": message_type,
        "queued_at": datetime.now(IST).isoformat(),
        "status": "pending",
    }

    data_store.queue_whatsapp_message(entry)

    logger.info(
        "[WhatsApp Queue] Queued %s message for %s",
        message_type,
        phone,
    )

    return {
        "status": "queued",
        "phone": phone,
        "message_type": message_type,
        "queued_at": entry["queued_at"],
    }


def queue_post_call_thankyou(phone: str, customer_name: str) -> dict:
    """Queue a post-call thank you message after a conversation."""
    message = (
        f"Hello {customer_name}! 🙏\n\n"
        f"Thank you for your time on the call today with {BRAND_NAME}.\n\n"
        f"If you have any questions about the {PRODUCT_NAME} automated Gold & Forex trading subscription, "
        f"feel free to reach out anytime.\n\n"
        f"🌐 {COMPANY_WEBSITE}\n"
        f"📞 {COMPANY_PHONE}\n\n"
        f"— Team {BRAND_NAME}"
    )
    return queue_whatsapp_message(phone, message, "post_call_thanks")


def queue_subscription_details(phone: str, customer_name: str) -> dict:
    """Queue subscription plan details message via WhatsApp."""
    message = (
        f"Hello {customer_name}! 📊\n\n"
        f"Here are the *{PRODUCT_NAME}* subscription details from {BRAND_NAME}:\n\n"
        f"💰 *One-Time Lifetime Fee:* $100 (USD) / ₹10,000 (INR)\n"
        f"📈 *Profit Sharing:* 50/50 split\n"
        f"⏱️ *Setup Time:* 5 min to 24 hours\n"
        f"💵 *Starting Capital:* $500 - $1,000 (cent account)\n"
        f"🕐 *Operation:* 24/5 (Mon-Fri)\n"
        f"📊 *Performance Targets:*\n"
        f"   • Daily growth: 0.75% - 1.5%\n"
        f"   • Monthly returns: 15% - 25%\n"
        f"   • Accuracy: ~60%\n"
        f"   • Drawdown control: 5% - 10%\n"
        f"   • Risk cap: 4% - 5%\n\n"
        f"⚠️ *Disclaimer:* Past performance does not guarantee future results. "
        f"Trading always carries risk.\n\n"
        f"Ready to get started? Reply to this message or call us!\n\n"
        f"🌐 {COMPANY_WEBSITE}\n"
        f"📞 {COMPANY_PHONE}\n\n"
        f"— Team {BRAND_NAME}"
    )
    return queue_whatsapp_message(phone, message, "subscription_details")


def queue_demo_confirmation(phone: str, customer_name: str, demo_time: str) -> dict:
    """Queue demo call confirmation message."""
    message = (
        f"✅ *Demo Call Confirmed!*\n\n"
        f"Hello {customer_name}!\n\n"
        f"Your demo call with the *{BRAND_NAME}* team has been scheduled:\n"
        f"📅 {demo_time}\n\n"
        f"During the demo, our team will:\n"
        f"• Walk you through the *{PRODUCT_NAME}* setup process\n"
        f"• Show you the trading dashboard live\n"
        f"• Answer all your questions\n\n"
        f"If you need to reschedule, just reply to this message.\n\n"
        f"🌐 {COMPANY_WEBSITE}\n"
        f"📞 {COMPANY_PHONE}\n\n"
        f"— Team {BRAND_NAME}"
    )
    return queue_whatsapp_message(phone, message, "demo_confirmation")


def get_pending_queue() -> list[dict]:
    """Get all pending (unsent) messages from the queue."""
    from app.core.data_store import data_store
    queue = data_store.get_whatsapp_queue()
    return [msg for msg in queue if msg.get("status") == "pending"]


def send_subscription_info(phone: str, customer_name: str) -> dict:
    """
    Send subscription plan details via WhatsApp.

    Args:
        phone: Customer phone number
        customer_name: Customer's name for personalization
    """
    message = (
        f"📊 {COMPANY_NAME} — Subscription Plan Details\n\n"
        f"Hello {customer_name}!\n\n"
        f"Here's everything you need to know about our AI-powered trading system:\n\n"
        f"💰 Lifetime Access: $100 / ₹10,000 (one-time)\n"
        f"📈 Profit Split: 50/50\n"
        f"⏱️ Setup: 5 min to 24 hours\n"
        f"💵 Capital: $500 - $1,000 (cent account)\n"
        f"🕐 Trades: 24 hours/day, 5 days/week\n\n"
        f"⚠️ Past performance does not guarantee future results. Trading carries risk.\n\n"
        f"Questions? Call us at {COMPANY_PHONE}\n"
        f"🌐 {COMPANY_WEBSITE}\n\n"
        f"— Team {COMPANY_NAME}"
    )

    return send_whatsapp_message(phone, message)


def send_follow_up_message(phone: str, customer_name: str, context: str = "") -> dict:
    """
    Send a follow-up WhatsApp message after a call.

    Args:
        phone: Customer phone number
        customer_name: Customer's name
        context: Brief context about the call outcome
    """
    message = (
        f"Hello {customer_name}! 🙏\n\n"
        f"Thank you for your time on the call today.\n\n"
        f"{context}\n\n"
        f"Feel free to reach out whenever you're ready to discuss further.\n\n"
        f"🌐 {COMPANY_WEBSITE}\n"
        f"📞 {COMPANY_PHONE}\n\n"
        f"— Team {COMPANY_NAME}"
    )

    return send_whatsapp_message(phone, message)


def send_appointment_reminder(phone: str, customer_name: str, slot: str) -> dict:
    """
    Send demo/appointment reminder via WhatsApp.

    Args:
        phone: Customer phone number
        customer_name: Customer's name
        slot: Appointment/demo slot (e.g., "Saturday June 7 at 3 PM")
    """
    message = (
        f"📊 Demo Call Reminder\n\n"
        f"Hello {customer_name}!\n\n"
        f"Just a friendly reminder about your upcoming demo call:\n\n"
        f"📅 {slot}\n\n"
        f"Our team will walk you through the Alpha Bot AI trading system "
        f"and answer all your questions.\n\n"
        f"If you need to reschedule, just reply to this message or call us.\n\n"
        f"🌐 {COMPANY_WEBSITE}\n"
        f"📞 {COMPANY_PHONE}\n\n"
        f"— Team {COMPANY_NAME}"
    )

    return send_whatsapp_message(phone, message)
