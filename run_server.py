"""
FastAPI Server — Entry Point
==============================
Starts the operator dashboard and REST API server.

Usage:
    python run_server.py

Opens the dashboard at http://localhost:8000
"""

import sys
import os
import threading
import webbrowser
import logging

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

import uvicorn

from app.config.settings import settings
from app.server.app import create_app

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger(__name__)

app = create_app()


def main():
    """Start the FastAPI server and open the dashboard."""
    logger.info("Starting Alpha Bot AI Gold & Forex Trading Subscription Agent Server")
    logger.info("Dashboard: http://localhost:%d", settings.port)
    logger.info("LiveKit URL: %s", settings.livekit_url)
    logger.info("SIP Trunk: %s", settings.sip_outbound_trunk_id)
    logger.info("TTS Voice: %s", settings.sarvam_tts_speaker)
    logger.info("LLM: %s", "Sarvam sarvam-m" if settings.use_sarvam_llm else "GPT-4o-mini")

    # Open browser after short delay
    threading.Timer(
        1.5, lambda: webbrowser.open(f"http://localhost:{settings.port}")
    ).start()

    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
