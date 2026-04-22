"""ASGI entry point for Render (and local dev).

Start locally:
    uvicorn app:app --reload

Render start command (set in render.yaml):
    uvicorn app:app --host 0.0.0.0 --port $PORT
"""
from agent.webhooks import build_app

app = build_app()
