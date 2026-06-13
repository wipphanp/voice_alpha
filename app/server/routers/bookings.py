"""Bookings API — read booking and call outcome records."""

from fastapi import APIRouter

from app.core.data_store import data_store

router = APIRouter()


@router.get("")
async def get_bookings():
    """Return all bookings and call outcomes."""
    return data_store.get_bookings()
