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

app = FastAPI(title="Tenacious Conversion Engine API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    """Run the full orchestrator synchronously — called in a thread."""
    prospects = load_synthetic_prospects()
    match = next(
        (p for p in prospects if p["id"] == prospect_id or p.get("crunchbase_id") == prospect_id),
        None,
    )
    if not match:
        return {"error": f"Prospect {prospect_id} not found"}
    orch = Orchestrator()
    result = orch.run_one(match, simulate_reply=True)
    return result.__dict__


@app.get("/api/run/{prospect_id}")
async def run_pipeline(prospect_id: str):
    async def generate():
        # Stream each step as "running" while the pipeline warms up
        for step_id, label in PIPELINE_STEPS:
            yield f"data: {json.dumps({'type': 'step', 'step': step_id, 'label': label, 'status': 'running'})}\n\n"
            await asyncio.sleep(0.3)

        # Run the full pipeline in a thread (it's synchronous I/O)
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(_run_pipeline_sync, prospect_id),
                timeout=300,  # 5 minutes — allows for LLM + Resend + Cal.com calls
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
