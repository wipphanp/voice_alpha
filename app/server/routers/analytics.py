"""
Analytics API router.

Provides endpoints for call analytics, lead scoring, and reporting.
"""

from fastapi import APIRouter

from app.core.analytics import get_analytics, get_lead_analytics, get_all_leads_with_scores, generate_report
from app.core.scheduler import call_scheduler

router = APIRouter()


@router.get("/")
async def get_call_analytics():
    """
    Get overall call analytics and statistics.

    Returns total calls, bookings, conversion rate, outcome breakdown,
    avg call duration, lead score breakdown, and per-lead averages.
    """
    return get_analytics()


@router.get("/leads")
async def get_leads_with_scores():
    """
    Get all leads with their scores.

    Returns list of leads with phone, name, status, score, and last outcome.
    Lead scores: hot (booked), warm (callback), cold (not interested), dead (dnc).
    """
    return get_all_leads_with_scores()


@router.get("/report/{period}")
async def get_report(period: str = "daily"):
    """
    Generate a daily or weekly report summary.

    Args:
        period: 'daily' or 'weekly'
    """
    if period not in ("daily", "weekly"):
        period = "daily"
    return generate_report(period)


@router.get("/lead/{phone}")
async def get_lead_stats(phone: str):
    """
    Get analytics for a specific lead.

    Args:
        phone: Customer phone number (URL encoded if needed, e.g., +919876543210)
    """
    # URL decode the phone (+ might come as %2B)
    if not phone.startswith("+"):
        phone = f"+{phone}"
    return get_lead_analytics(phone)


@router.get("/scheduler")
async def get_scheduler_status():
    """
    Get current scheduler status — callable now, optimal window,
    and all call attempts.
    """
    return {
        "is_callable_now": call_scheduler.is_callable_now(),
        "is_optimal_window": call_scheduler.is_optimal_window(),
        "call_attempts": call_scheduler.get_all_attempts(),
    }
