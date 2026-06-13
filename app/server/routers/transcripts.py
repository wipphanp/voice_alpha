"""Transcripts API — list, view, and download call transcripts + summaries."""

import json
import logging

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

from app.core.transcript import get_transcripts, TRANSCRIPTS_DIR

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("")
async def list_transcripts():
    """List all call transcripts with their summaries and metadata."""
    return get_transcripts()


@router.get("/{filename}")
async def get_transcript(filename: str):
    """
    Return a single transcript.

    - ``.txt`` → downloads the human-readable transcript file.
    - ``.json`` → returns the structured record (turns + summary).
    """
    file_path = TRANSCRIPTS_DIR / filename

    # Guard against path traversal — only serve files inside the dir.
    try:
        file_path.resolve().relative_to(TRANSCRIPTS_DIR.resolve())
    except ValueError:
        return JSONResponse({"error": "Invalid filename"}, status_code=400)

    if not file_path.exists():
        return JSONResponse({"error": "Transcript not found"}, status_code=404)

    if filename.endswith(".json"):
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            return data
        except (json.JSONDecodeError, OSError) as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    if filename.endswith(".txt"):
        return FileResponse(file_path, media_type="text/plain", filename=filename)

    return JSONResponse({"error": "Unsupported file type"}, status_code=400)
