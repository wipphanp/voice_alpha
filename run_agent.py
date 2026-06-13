"""
LiveKit Agent Worker — Entry Point
====================================
Starts the LiveKit agent worker that handles voice conversations.

Usage:
    python run_agent.py dev        # Development mode (auto-reload)
    python run_agent.py start      # Production mode

The agent automatically joins LiveKit rooms created by the server
and handles the full STT → LLM → TTS voice pipeline.
"""

import sys
import os

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from livekit.agents import AgentServer, JobContext, JobProcess, cli
from livekit.plugins import silero

from app.agent.entrypoint import entrypoint


def prewarm(proc: JobProcess) -> None:
    """
    Process-level prewarm — runs ONCE per worker process at startup.

    Loads the Silero VAD model a single time and stashes it in the process
    userdata so every session in this process reuses the same instance,
    instead of paying the load cost (latency + memory) on every call.
    """
    proc.userdata["vad"] = silero.VAD.load(
        min_speech_duration=0.05,     # 50ms — detect speech almost instantly
        min_silence_duration=0.3,     # 300ms silence = quick turn boundary
        activation_threshold=0.5,     # Default sensitivity — avoids false triggers on noise
    )


server = AgentServer(setup_fnc=prewarm)


@server.rtc_session
async def session_entrypoint(ctx: JobContext):
    await entrypoint(ctx)


if __name__ == "__main__":
    cli.run_app(server)
