"""
Call Analytics/Reporting.

Computes stats from bookings data: total calls, conversion rates,
outcome breakdowns, per-lead metrics, lead scoring, and report generation.
"""

import logging
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.data_store import data_store
from app.config.constants import VALID_OUTCOMES

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")

# Lead scoring rules for trading agent
LEAD_SCORE_MAP = {
    "interested_demo_scheduled": "hot",
    "subscribed": "hot",
    "callback_requested": "warm",
    "customer_busy_reschedule": "warm",
    "not_interested_now": "cold",
    "dnc_requested": "dead",
    "wrong_number": "dead",
}


def compute_lead_score(outcome: str) -> str:
    """
    Compute lead score based on the latest call outcome.

    Args:
        outcome: Call outcome string

    Returns:
        Score: hot, warm, cold, or dead
    """
    return LEAD_SCORE_MAP.get(outcome, "cold")


def get_analytics() -> dict:
    """
    Compute analytics from bookings.json data.

    Returns:
        dict with total_calls, total_demos, conversion_rate,
        outcome_breakdown, avg_calls_per_lead, avg_call_duration,
        lead_scores, and recent_activity.
    """
    bookings = data_store.get_bookings()

    if not bookings:
        return {
            "total_calls": 0,
            "total_demos_scheduled": 0,
            "total_subscriptions": 0,
            "conversion_rate": 0.0,
            "outcome_breakdown": {},
            "avg_calls_per_lead": 0.0,
            "avg_call_duration_seconds": 0.0,
            "unique_leads_contacted": 0,
            "lead_score_breakdown": {},
            "recent_activity": [],
        }

    # Count total call outcomes (entries with 'outcome' field)
    call_outcomes = [b for b in bookings if "outcome" in b]
    total_calls = len(call_outcomes)

    # Count demo bookings
    demo_bookings = [b for b in bookings if b.get("type") == "demo_scheduled"]
    total_demos = len(demo_bookings)

    # Count subscriptions
    subscriptions = [b for b in bookings if b.get("outcome") == "subscribed"]
    total_subscriptions = len(subscriptions)

    # Conversion rate: demos / total call interactions
    conversion_rate = (total_demos / total_calls * 100) if total_calls > 0 else 0.0

    # Outcome breakdown
    outcome_counter = Counter()
    for entry in call_outcomes:
        outcome = entry.get("outcome", "unknown")
        outcome_counter[outcome] += 1

    # Average call duration from tracked durations
    durations = data_store.get_call_durations()
    avg_duration = 0.0
    if durations:
        avg_duration = sum(d.get("duration_seconds", 0) for d in durations) / len(durations)

    # Unique leads contacted
    unique_phones = set()
    for entry in bookings:
        phone = entry.get("customer_phone", "")
        if phone:
            unique_phones.add(phone)
    unique_leads_contacted = len(unique_phones)

    # Average calls per lead
    avg_calls_per_lead = (
        total_calls / unique_leads_contacted
        if unique_leads_contacted > 0
        else 0.0
    )

    # Lead score breakdown
    lead_scores = data_store.get_lead_scores()
    score_counter = Counter(lead_scores.values())

    # Recent activity (last 10 entries)
    recent_activity = []
    for entry in bookings[-10:]:
        recent_activity.append({
            "timestamp": entry.get("booked_at", ""),
            "customer_phone": entry.get("customer_phone", ""),
            "type": entry.get("type", "call_outcome"),
            "outcome": entry.get("outcome", entry.get("type", "")),
            "notes": entry.get("notes", ""),
        })

    return {
        "total_calls": total_calls,
        "total_demos_scheduled": total_demos,
        "total_subscriptions": total_subscriptions,
        "conversion_rate": round(conversion_rate, 2),
        "outcome_breakdown": dict(outcome_counter),
        "avg_calls_per_lead": round(avg_calls_per_lead, 2),
        "avg_call_duration_seconds": round(avg_duration, 1),
        "unique_leads_contacted": unique_leads_contacted,
        "lead_score_breakdown": dict(score_counter),
        "recent_activity": recent_activity,
    }


def get_lead_analytics(phone: str) -> dict:
    """
    Get analytics for a specific lead.

    Args:
        phone: Customer phone number

    Returns:
        dict with call history, outcomes, and lead score.
    """
    bookings = data_store.get_bookings()

    lead_entries = [b for b in bookings if b.get("customer_phone") == phone]
    call_outcomes = [b for b in lead_entries if "outcome" in b]
    demos = [b for b in lead_entries if b.get("type") == "demo_scheduled"]

    outcome_counter = Counter()
    for entry in call_outcomes:
        outcome_counter[entry.get("outcome", "unknown")] += 1

    # Get lead score
    lead_scores = data_store.get_lead_scores()
    score = lead_scores.get(phone, "unknown")

    return {
        "phone": phone,
        "total_interactions": len(lead_entries),
        "total_calls": len(call_outcomes),
        "total_demos": len(demos),
        "outcome_breakdown": dict(outcome_counter),
        "lead_score": score,
        "last_interaction": lead_entries[-1].get("booked_at", "") if lead_entries else "",
        "history": lead_entries,
    }


def get_all_leads_with_scores() -> list[dict]:
    """
    Get all leads with their scores for the /api/analytics/leads endpoint.

    Returns:
        List of lead dicts with phone, name, status, score, last_outcome.
    """
    leads = data_store.get_leads()
    lead_scores = data_store.get_lead_scores()

    result = []
    for lead in leads:
        phone = lead.get("phone", "")
        result.append({
            "phone": phone,
            "name": lead.get("name", ""),
            "status": lead.get("status", "pending"),
            "score": lead_scores.get(phone, "unknown"),
            "outcome": lead.get("outcome", ""),
        })

    return result


def generate_report(period: str = "daily") -> dict:
    """
    Generate a daily or weekly report summary.

    Args:
        period: "daily" or "weekly"

    Returns:
        dict with report summary for the given period.
    """
    bookings = data_store.get_bookings()
    now = datetime.now(IST)

    if period == "weekly":
        cutoff = now - timedelta(days=7)
    else:
        cutoff = now - timedelta(days=1)

    cutoff_str = cutoff.isoformat()

    # Filter entries within the period
    period_entries = []
    for entry in bookings:
        booked_at = entry.get("booked_at", "")
        if booked_at >= cutoff_str:
            period_entries.append(entry)

    call_outcomes = [e for e in period_entries if "outcome" in e]
    demo_bookings = [e for e in period_entries if e.get("type") == "demo_scheduled"]

    total_calls = len(call_outcomes)
    total_demos = len(demo_bookings)
    conversion_rate = (total_demos / total_calls * 100) if total_calls > 0 else 0.0

    outcome_counter = Counter()
    for entry in call_outcomes:
        outcome_counter[entry.get("outcome", "unknown")] += 1

    # Average call duration for period
    durations = data_store.get_call_durations()
    period_durations = [d for d in durations if d.get("timestamp", "") >= cutoff_str]
    avg_duration = 0.0
    if period_durations:
        avg_duration = sum(d.get("duration_seconds", 0) for d in period_durations) / len(period_durations)

    unique_phones = set()
    for entry in period_entries:
        phone = entry.get("customer_phone", "")
        if phone:
            unique_phones.add(phone)

    logger.info("Generated %s report: %d calls, %d demos", period, total_calls, total_demos)

    return {
        "period": period,
        "from": cutoff.isoformat(),
        "to": now.isoformat(),
        "total_calls": total_calls,
        "total_demos_scheduled": total_demos,
        "conversion_rate": round(conversion_rate, 2),
        "outcome_breakdown": dict(outcome_counter),
        "avg_call_duration_seconds": round(avg_duration, 1),
        "unique_leads_contacted": len(unique_phones),
    }
