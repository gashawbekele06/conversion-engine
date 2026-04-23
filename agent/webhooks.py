"""FastAPI webhook handlers — reply ingestion from Resend, Africa's Talking, Cal.com, HubSpot.

Endpoints:
  GET  /healthz              — liveness probe
  POST /webhooks/email       ← Resend reply webhook
  POST /webhooks/sms         ← Africa's Talking inbound SMS callback
  POST /webhooks/calcom      ← Cal.com booking events (BOOKING_CREATED, CANCELLED, RESCHEDULED)
  POST /webhooks/hubspot     ← HubSpot contact/deal property-change events

All handlers append to eval/traces/inbox.jsonl for audit. The same public
Render URL is registered once across all four integrations.

Safe to import without FastAPI installed — the app object is lazily
built only when `build_app()` is called.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from typing import Any

from .channels.hubspot import HubSpotChannel
from .channels.sms import SMSChannel
from .config import load_config
from .tracing import get_tracer


def _verify_calcom_signature(body: bytes, signature_header: str | None) -> bool:
    """Verify Cal.com X-Cal-Signature-256 header (HMAC-SHA256 over raw body)."""
    secret = os.getenv("CALCOM_WEBHOOK_SECRET", "")
    if not secret:
        return True  # secret not configured → skip verification (dev mode)
    if not signature_header:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header.lstrip("sha256="))


def _verify_hubspot_signature(body: bytes, signature_header: str | None) -> bool:
    """Verify HubSpot X-HubSpot-Signature-V3 header."""
    secret = os.getenv("HUBSPOT_WEBHOOK_SECRET", "")
    if not secret:
        return True
    if not signature_header:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def build_app():  # pragma: no cover — smoke-tested separately
    from fastapi import FastAPI, HTTPException, Request

    app = FastAPI(title="Tenacious Conversion Engine webhooks", docs_url=None, redoc_url=None)

    sms_channel = SMSChannel()
    hubspot_channel = HubSpotChannel()
    inbox_path = Path(__file__).resolve().parents[1] / "eval" / "traces" / "inbox.jsonl"
    inbox_path.parent.mkdir(parents=True, exist_ok=True)

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:  # noqa: D401
        cfg = load_config()
        return {"status": "ok", "tenacious_live": cfg.tenacious_live,
                "llm_tier": cfg.llm_tier}

    # ------------------------------------------------------------------ email
    @app.post("/webhooks/email")
    async def email_webhook(request: Request) -> dict[str, Any]:
        payload = await request.json()
        tracer = get_tracer()
        with tracer.trace("webhook.email", subject=payload.get("subject")) as attrs:
            _append(inbox_path, {"channel": "email", "ts": time.time(), "payload": payload})
            attrs["from"] = payload.get("from")
            return {"ok": True}

    # -------------------------------------------------------------------- sms
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

    # ----------------------------------------------------------------- cal.com
    @app.post("/webhooks/calcom")
    async def calcom_webhook(request: Request) -> dict[str, Any]:
        body = await request.body()
        sig = request.headers.get("X-Cal-Signature-256")
        if not _verify_calcom_signature(body, sig):
            raise HTTPException(status_code=401, detail="invalid cal.com signature")

        payload = json.loads(body)
        tracer = get_tracer()
        event_type = payload.get("triggerEvent", payload.get("type", "unknown"))

        with tracer.trace("webhook.calcom", event=event_type) as attrs:
            booking = payload.get("payload", {})
            prospect_email = (booking.get("attendees") or [{}])[0].get("email", "")
            booking_id = str(booking.get("uid", ""))
            when_iso = booking.get("startTime", "")

            attrs["event"] = event_type
            attrs["prospect"] = prospect_email
            attrs["booking_id"] = booking_id

            row = {
                "channel": "calcom",
                "ts": time.time(),
                "event": event_type,
                "booking_id": booking_id,
                "prospect_email": prospect_email,
                "when_iso": when_iso,
                "payload": payload,
            }
            _append(inbox_path, row)

            # Mirror booking state into HubSpot mock
            if prospect_email and event_type == "BOOKING_CREATED":
                try:
                    hubspot_channel.mark_meeting_booked(
                        email=prospect_email,
                        when_iso=when_iso,
                        calcom_booking_id=booking_id,
                    )
                except Exception:  # noqa: BLE001
                    pass  # HubSpot write is best-effort; don't fail the webhook

            return {"ok": True, "event": event_type, "booking_id": booking_id}

    # --------------------------------------------------------------- hubspot
    @app.post("/webhooks/hubspot")
    async def hubspot_webhook(request: Request) -> dict[str, Any]:
        body = await request.body()
        sig = request.headers.get("X-HubSpot-Signature-V3")
        if not _verify_hubspot_signature(body, sig):
            raise HTTPException(status_code=401, detail="invalid hubspot signature")

        events = json.loads(body)  # HubSpot sends a JSON array
        if not isinstance(events, list):
            events = [events]

        tracer = get_tracer()
        with tracer.trace("webhook.hubspot", count=len(events)) as attrs:
            attrs["event_types"] = list({e.get("subscriptionType", "?") for e in events})
            for event in events:
                _append(inbox_path, {
                    "channel": "hubspot",
                    "ts": time.time(),
                    "event": event.get("subscriptionType"),
                    "object_id": event.get("objectId"),
                    "payload": event,
                })
            return {"ok": True, "processed": len(events)}

    return app


def _append(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, default=str) + "\n")
