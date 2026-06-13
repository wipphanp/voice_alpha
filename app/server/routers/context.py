"""Context API — returns broker configuration and runtime info."""

from fastapi import APIRouter

from app.core.context import get_runtime_context

router = APIRouter()


@router.get("/context")
async def api_context():
    """Return broker configuration, current date, and available slots."""
    return get_runtime_context()
