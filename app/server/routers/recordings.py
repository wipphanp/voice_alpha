"""Recordings API — list, download, and upload call recordings."""

import logging
from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from app.core.call_recorder import get_recordings
from app.config.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter()

RECORDINGS_DIR = settings.data_dir / "recordings"
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)


@router.get("")
async def list_recordings():
    """List all call recordings with metadata."""
    return get_recordings()


@router.get("/{filename}")
async def download_recording(filename: str):
    """Download a specific recording WAV file."""
    file_path = RECORDINGS_DIR / filename
    if not file_path.exists() or not file_path.name.endswith((".wav", ".webm")):
        return JSONResponse({"error": "Recording not found"}, status_code=404)
    media_type = "audio/wav" if filename.endswith(".wav") else "audio/webm"
    return FileResponse(file_path, media_type=media_type, filename=filename)


@router.post("/upload-customer")
async def upload_customer_audio(
    audio: UploadFile = File(...),
    room_name: str = Form(""),
):
    """
    Receive HD customer audio recorded in the browser (pre-Opus quality).
    Saved alongside the agent recording for the same call.
    """
    if not audio.filename:
        return JSONResponse({"error": "No file"}, status_code=400)

    # Save the raw browser recording
    filename = audio.filename or f"customer_{room_name}.webm"
    dest = RECORDINGS_DIR / filename
    content = await audio.read()
    dest.write_bytes(content)

    size_kb = len(content) / 1024
    logger.info("Customer HD audio saved: %s (%.1f KB, room: %s)", filename, size_kb, room_name)

    return {"ok": True, "filename": filename, "size_bytes": len(content)}
