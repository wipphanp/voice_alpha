"""
Runtime context computation — dynamic IST dates, brand/company info.
"""

from datetime import datetime, timedelta, timezone

from app.config.constants import (
    BRAND_NAME,
    PRODUCT_NAME,
    COMPANY_PHONE,
    COMPANY_EMAIL,
    COMPANY_WEBSITE,
)

IST = timezone(timedelta(hours=5, minutes=30))


def get_runtime_context() -> dict:
    """
    Compute fresh runtime context for every call.
    Returns brand info + current timestamp.
    """
    now = datetime.now(IST)

    return {
        "today_human":   now.strftime("%A, %B %d, %Y at %I:%M %p IST"),
        "brand_name":    BRAND_NAME,
        "product_name":  PRODUCT_NAME,
        "company_name":  BRAND_NAME,   # legacy alias
        "company_phone": COMPANY_PHONE,
        "company_email": COMPANY_EMAIL,
        "company_website": COMPANY_WEBSITE,
    }
