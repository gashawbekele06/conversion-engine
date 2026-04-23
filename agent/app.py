"""ASGI entry point — exposes the FastAPI app for uvicorn.

    uvicorn agent.app:app --reload --port 8000
"""
from .webhooks import build_app

app = build_app()
