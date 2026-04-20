"""FastAPI webhook handlers — reply ingestion from Resend/MailerSend + SMS.

Wiring:
  - POST /webhooks/email  ← Resend/MailerSend reply webhook
  - POST /webhooks/sms    ← Africa's Talking inbound SMS webhook

Both handlers route inbound into the orchestrator's conversation-state
store. Handles STOP/HELP/UNSUB for SMS per TCPA semantics.

Safe to import without FastAPI installed — the app object is lazily
built only when `build_app()` is called.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .channels.sms import SMSChannel
from .config import load_config
from .tracing import get_tracer


def build_app():  # pragma: no cover — smoke-tested separately
    from fastapi import FastAPI, Request

    app = FastAPI(title="Tenacious Conversion Engine webhooks")

    sms_channel = SMSChannel()
    inbox_path = Path(__file__).resolve().parents[1] / "eval" / "traces" / "inbox.jsonl"
    inbox_path.parent.mkdir(parents=True, exist_ok=True)

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:  # noqa: D401
        cfg = load_config()
        return {"status": "ok", "tenacious_live": cfg.tenacious_live,
                "llm_tier": cfg.llm_tier}

    @app.post("/webhooks/email")
    async def email_webhook(request: Request) -> dict[str, Any]:
        payload = await request.json()
        tracer = get_tracer()
        with tracer.trace("webhook.email", subject=payload.get("subject")) as attrs:
            _append(inbox_path, {"channel": "email", "ts": time.time(), "payload": payload})
            attrs["from"] = payload.get("from")
            return {"ok": True}

    @app.post("/webhooks/sms")
    async def sms_webhook(request: Request) -> dict[str, Any]:
        payload = await request.json()
        tracer = get_tracer()
        text = payload.get("text", "")
        frm = payload.get("from", "")
        with tracer.trace("webhook.sms", from_=frm) as attrs:
            kind = sms_channel.classify_inbound(text)
            attrs["kind"] = kind
            row = {"channel": "sms", "ts": time.time(), "from": frm,
                   "text": text, "classified": kind}
            _append(inbox_path, row)
            if kind == "stop":
                return {"ok": True, "reply": "You're opted out. Reply HELP for info."}
            if kind == "help":
                return {"ok": True,
                        "reply": "Tenacious outbound. Reply STOP to opt out. Msg&data rates may apply."}
            return {"ok": True}

    return app


def _append(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, default=str) + "\n")
