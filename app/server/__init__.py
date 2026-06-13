"""FastAPI server module — REST API for the operator dashboard."""

from .app import create_app

__all__ = ["create_app"]
