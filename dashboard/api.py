"""FastAPI backend for Tenacious Conversion Engine Demo Dashboard.

Run:  .venv/Scripts/uvicorn dashboard.api:app --reload --port 8000
      (from the conversion-engine/ root)
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

# Load .env FIRST — before any agent imports — so all credentials are in os.environ
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)
except ImportError:
    pass

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

# Import orchestrator AFTER .env is loaded
from agent.orchestrator import Orchestrator, load_synthetic_prospects  # noqa: E402
from agent.channels.gmail_poller import get_poller  # noqa: E402

# NOTE: Frontend is served by the Vite dev server on http://localhost:5173
# Run: cd dashboard/app && npm run dev
# DIST path kept for reference only — static serving removed.
DIST = Path(__file__).parent / "app" / "dist"

app = FastAPI(title="Tenacious Conversion Engine API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _startup() -> None:
    """Start the Gmail IMAP poller when the API server boots."""
    poller = get_poller()
    if poller.is_configured():
        poller.start()
    else:
        import logging
        logging.getLogger(__name__).info(
            "Gmail IMAP poller not started — IMAP credentials not set. "
            "Dashboard will show manual reply button as fallback."
        )

DIST = Path(__file__).parent / "app" / "dist"


def _load(path: str) -> dict | list:
    return json.loads((BASE / path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Prospects
# ---------------------------------------------------------------------------

@app.get("/api/prospects")
def get_prospects():
    data = _load("data/synthetic_prospects.json")
    return [p for p in data["prospects"] if p["id"].startswith("prospect_")]


# ---------------------------------------------------------------------------
# Hiring Signal Brief  (generated live)
# ---------------------------------------------------------------------------

@app.get("/api/brief/{crunchbase_id}")
def get_brief(crunchbase_id: str):
    from agent.enrichment.brief_generator import build_hiring_signal_brief
    return build_hiring_signal_brief(crunchbase_id)


# ---------------------------------------------------------------------------
# Competitor Gap Brief
# ---------------------------------------------------------------------------

@app.get("/api/gap/{crunchbase_id}")
def get_gap(crunchbase_id: str):
    data = _load("eval/traces/competitor_gap_brief.json")
    return data["briefs"].get(crunchbase_id, {"error": "not_found"})


# ---------------------------------------------------------------------------
# Email (latest for prospect)
# ---------------------------------------------------------------------------

@app.get("/api/email/{prospect_id}")
def get_email(prospect_id: str):
    lines = (BASE / "eval/traces/email_sink.jsonl").read_text(encoding="utf-8").splitlines()
    rows = [json.loads(l) for l in lines if l.strip() and prospect_id in l]
    return rows[-1] if rows else {"error": "not_found"}


# ---------------------------------------------------------------------------
# Inbox — real reply detection (read by dashboard polling loop)
# Returns the most recent reply event for a prospect from inbox.jsonl.
# The Gmail IMAP poller writes here when a real reply arrives.
# ---------------------------------------------------------------------------

@app.get("/api/inbox/{prospect_id}")
def get_inbox_reply(prospect_id: str):
    """Return the latest reply event in inbox.jsonl for this prospect.

    The dashboard polls this every 5 s after an email is sent.
    When the Gmail IMAP poller detects a real reply it writes to inbox.jsonl
    and fires the Cal.com + HubSpot handlers. This endpoint surfaces the
    reply text so the dashboard can update the conversation tab and journey
    banner without a page reload.
    """
    inbox_path = BASE / "eval/traces/inbox.jsonl"
    if not inbox_path.exists():
        return {"error": "not_found"}

    # Resolve the prospect email so we can match against inbox FROM field
    try:
        data = _load("data/synthetic_prospects.json")
        prospects = data.get("prospects", data) if isinstance(data, dict) else data
        prospect = next(
            (p for p in prospects if p["id"] == prospect_id),
            None,
        )
    except Exception:
        prospect = None

    prospect_email = prospect["contact"]["email"] if prospect else None
    # Also accept the staff sink email (kill switch routes outbound there).
    # Read from config so it matches whatever is set in .env — never hardcode.
    from agent.config import load_config as _load_cfg
    staff_sink = _load_cfg().staff_sink_email.lower()

    # Look up the sent subject for this prospect so we can disambiguate
    # when multiple staff-sink replies exist (one per prospect).
    sent_subject = None
    email_sink_path = BASE / "eval/traces/email_sink.jsonl"
    if email_sink_path.exists():
        for sl in email_sink_path.read_text(encoding="utf-8").splitlines():
            if not sl.strip():
                continue
            try:
                sr = json.loads(sl)
            except Exception:
                continue
            if sr.get("metadata", {}).get("prospect_id") == prospect_id:
                sent_subject = (sr.get("subject") or "").lower()
                break  # first match is sufficient

    lines = inbox_path.read_text(encoding="utf-8").splitlines()
    reply_events = []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if row.get("channel") != "email":
            continue
        kind = row.get("kind", "")
        if kind not in ("reply_positive", "reply_negative", "reply_other"):
            continue
        from_addr = (row.get("from") or row.get("payload", {}).get("from") or "").lower()
        reply_subj = (row.get("subject") or row.get("payload", {}).get("subject") or "").lower()
        # Match if the reply came from the prospect's email directly
        if prospect_email and from_addr == prospect_email.lower():
            reply_events.append(row)
        elif from_addr == staff_sink:
            # Staff sink routes all prospects — disambiguate by subject.
            # A real Gmail reply subject looks like "Re: <sent_subject>".
            # If we know the sent subject, require it to appear in the reply subject.
            if sent_subject and sent_subject not in reply_subj:
                continue
            reply_events.append(row)

    if not reply_events:
        return {"error": "not_found"}

    latest = reply_events[-1]
    return {
        "kind": latest.get("kind"),
        "from": latest.get("from") or latest.get("payload", {}).get("from"),
        "subject": latest.get("subject") or latest.get("payload", {}).get("subject", ""),
        "text": (latest.get("payload") or {}).get("text") or "",
        "ts": latest.get("ts"),
        "source": (latest.get("payload") or {}).get("source", "webhook"),
    }


# ---------------------------------------------------------------------------
# HubSpot contact
# ---------------------------------------------------------------------------

@app.get("/api/hubspot/{email:path}")
def get_hubspot(email: str):
    data = _load("eval/traces/hubspot_mock.json")
    contacts = data.get("contacts", {})
    if email in contacts:
        return contacts[email]
    for v in contacts.values():
        if v.get("properties", {}).get("email") == email:
            return v
    return {"error": "not_found"}


# ---------------------------------------------------------------------------
# Cal.com booking
# ---------------------------------------------------------------------------

@app.get("/api/calcom/{email:path}")
def get_calcom(email: str):
    data = _load("eval/traces/calcom_mock.json")
    bookings = data.get("bookings", [])
    matches = []
    if isinstance(bookings, list):
        matches = [b for b in bookings if b.get("prospect_email") == email]
    elif isinstance(bookings, dict):
        matches = [v for v in bookings.values() if v.get("prospect_email") == email]
    # Return most recent booking (last appended)
    return matches[-1] if matches else {"error": "not_found"}


# ---------------------------------------------------------------------------
# Benchmark scores
# ---------------------------------------------------------------------------

@app.get("/api/bench")
def get_bench():
    return _load("eval/score_log.json")


# ---------------------------------------------------------------------------
# Gmail IMAP poller  (PATH A: real reply detection)
# ---------------------------------------------------------------------------

@app.get("/api/poller/status")
def get_poller_status():
    """Return current status of the Gmail IMAP poller."""
    return get_poller().status()


@app.post("/api/poller/start")
def start_poller():
    """(Re)start the Gmail IMAP poller."""
    p = get_poller()
    if not p.is_configured():
        return {
            "ok": False,
            "error": "missing_config",
            "detail": (
                "Set GMAIL_IMAP_USER, GMAIL_IMAP_APP_PASSWORD, and "
                "TENACIOUS_REPLY_TO in .env then restart the server."
            ),
        }
    p.start()
    return {"ok": True, "status": p.status()}


@app.post("/api/poller/stop")
def stop_poller():
    """Stop the Gmail IMAP poller."""
    get_poller().stop()
    return {"ok": True}


# ---------------------------------------------------------------------------
# SMS send  (warm-lead follow-up — fires after simulated reply)
# ---------------------------------------------------------------------------

def _send_sms_sync(prospect_id: str, message: str) -> dict:
    from agent.channels.sms import SMSChannel
    from agent.orchestrator import load_synthetic_prospects

    prospects = load_synthetic_prospects()
    prospect = next((p for p in prospects if p["id"] == prospect_id), None)
    if not prospect:
        return {"error": f"Prospect {prospect_id} not found"}

    sms = SMSChannel()
    result = sms.send(
        to=prospect["contact"].get("phone_e164", sms.config.staff_sink_sms),
        body=message,
        synthetic=True,   # routes to STAFF_SINK_SMS
        warm_lead=True,   # simulated reply qualifies as warm engagement
        metadata={"prospect_id": prospect_id, "channel": "sms_warm_followup"},
    )
    return {
        "ok": result.ok,
        "provider": result.provider,
        "to": result.to,
        "message_id": result.message_id,
        "is_sink": result.is_sink,
        "latency_ms": result.latency_ms,
        "error": result.error,
    }


@app.post("/api/sms-send/{prospect_id}")
async def send_sms(prospect_id: str, payload: dict):
    message = payload.get("message", "Hi — following up on our email. Worth a quick call?")
    try:
        result = await asyncio.to_thread(_send_sms_sync, prospect_id, message)
    except Exception as exc:
        result = {"error": str(exc)}
    return result


# ---------------------------------------------------------------------------
# Ablation results (P-028 fix evidence)
# ---------------------------------------------------------------------------

@app.get("/api/ablation")
def get_ablation():
    return _load("ablation_results.json")


# ---------------------------------------------------------------------------
# Evidence graph (Act V audit trail)
# ---------------------------------------------------------------------------

@app.get("/api/evidence")
def get_evidence():
    return _load("eval/traces/evidence_graph.json")


# ---------------------------------------------------------------------------
# Pipeline run  (GET with Server-Sent Events so EventSource works from React)
# ---------------------------------------------------------------------------

PIPELINE_STEPS = [
    ("enrich",   "Enriching 6 public signals"),
    ("classify", "Classifying ICP segment"),
    ("compose",  "Composing email via LLM"),
    ("gate",     "Kill-switch check"),
    ("send",     "Sending email → gashawbekelek@gmail.com via Resend"),
    ("crm",      "Upserting HubSpot CRM"),
    ("booking",  "Booking Cal.com discovery call"),
    ("trace",    "Writing JSONL trace"),
]

# Step index where each pipeline stage maps (for SSE progress)
STEP_IDS = [s[0] for s in PIPELINE_STEPS]


def _run_pipeline_sync(prospect_id: str) -> dict:
    """Run the full orchestrator synchronously — called in a thread.

    simulate_reply is always False: the pipeline sends the email and stops.
    The real reply comes from gashawbekelek@gmail.com via the Gmail IMAP poller.
    The poller fires the Cal.com booking and HubSpot update automatically.
    The dashboard polls /api/inbox/{prospect_id} every 5 s to detect the reply.
    """
    prospects = load_synthetic_prospects()
    match = next(
        (p for p in prospects if p["id"] == prospect_id or p.get("crunchbase_id") == prospect_id),
        None,
    )
    if not match:
        return {"error": f"Prospect {prospect_id} not found"}
    orch = Orchestrator()
    result = orch.run_one(match, simulate_reply=False)
    return result.__dict__


# ---------------------------------------------------------------------------
# Simulate inbound reply  (fires webhook handler directly — no real email)
# Used by the dashboard "Simulate Reply" button for the demo
# ---------------------------------------------------------------------------

@app.post("/api/reply/{prospect_id}")
async def simulate_reply_endpoint(prospect_id: str, payload: dict | None = None):
    """Fire a synthetic reply through the registered email reply handlers.

    This mirrors what Resend sends to POST /webhooks/email when a prospect
    manually replies.  Use this button in the dashboard to advance the
    pipeline past 'awaiting_reply' without needing a live Resend domain.
    """
    from agent.webhooks import _email_reply_handlers, _unwrap_inbound_payload

    prospects = load_synthetic_prospects()
    match = next(
        (p for p in prospects if p["id"] == prospect_id),
        None,
    )
    if not match:
        return {"error": f"Prospect {prospect_id} not found"}

    body_text = (payload or {}).get("text") or "Interested — worth 30 minutes."
    inbound = {
        "type": "email.received",
        "data": {
            "from": match["contact"]["email"],
            "subject": "Re: Your outreach",
            "text": body_text,
        },
    }
    flat = _unwrap_inbound_payload(inbound)
    kind = "reply_positive"

    results = []
    for handler in _email_reply_handlers:
        try:
            handler(kind=kind, from_addr=flat["from"],
                    subject=flat["subject"], payload=flat)
            results.append("ok")
        except Exception as exc:
            results.append(str(exc))

    return {"ok": True, "kind": kind, "from": flat["from"], "handler_results": results}


@app.get("/api/run/{prospect_id}")
async def run_pipeline(prospect_id: str):
    """Stream pipeline progress via Server-Sent Events.

    Sends the outbound email to gashawbekelek@gmail.com and stops.
    The real reply must come from Gmail → IMAP poller → Cal.com booking → HubSpot.
    Dashboard polls /api/inbox/{prospect_id} every 5 s for the reply.
    """
    async def generate():
        # Stream each step label as "running" so the UI shows progress
        for step_id, label in PIPELINE_STEPS:
            yield f"data: {json.dumps({'type': 'step', 'step': step_id, 'label': label, 'status': 'running'})}\n\n"
            await asyncio.sleep(0.3)

        # Run the full pipeline in a background thread (synchronous I/O)
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(_run_pipeline_sync, prospect_id),
                timeout=300,  # 5 min — allows for LLM + Resend + Cal.com calls
            )
        except asyncio.TimeoutError:
            result = {"error": "Pipeline timed out after 5 minutes"}
        except Exception as exc:
            result = {"error": str(exc)}

        # Mark all steps done
        for step_id, _ in PIPELINE_STEPS:
            yield f"data: {json.dumps({'type': 'step', 'step': step_id, 'status': 'done'})}\n\n"

        # Final event with full result
        yield f"data: {json.dumps({'type': 'complete', 'result': result}, default=str)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Frontend served independently via Vite dev server ───────────────────────
# Run:  cd dashboard/app && npm run dev   → http://localhost:5173
# Vite proxies /api/* → http://localhost:8000  (see vite.config.js)
# The backend is API-only; no static file serving needed here.
