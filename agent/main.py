"""CLI entry points.

  python -m agent.main enrich <crunchbase_id>
  python -m agent.main run-one <prospect_id>
  python -m agent.main run-all
  python -m agent.main serve  (uvicorn agent.webhooks:build_app --factory)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Load .env before any config/channel imports so os.getenv picks up all keys
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass

from .enrichment import build_competitor_gap_brief, build_hiring_signal_brief
from .orchestrator import Orchestrator, load_synthetic_prospects


def _cmd_enrich(args: argparse.Namespace) -> int:
    key = args.crunchbase_id
    # Accept either a crunchbase_id (cb_sample_*) or a prospect_id (prospect_*)
    if key.startswith("prospect_"):
        prospects = load_synthetic_prospects()
        match = next((p for p in prospects if p["id"] == key), None)
        if not match:
            print(f"No prospect {key}; options: {[p['id'] for p in prospects]}",
                  file=sys.stderr)
            return 1
        key = match["crunchbase_id"]
    brief = build_hiring_signal_brief(key)
    gap = build_competitor_gap_brief(key)
    print(json.dumps({"brief": brief, "competitor_gap": gap}, indent=2, default=str))
    return 0


def _cmd_run_one(args: argparse.Namespace) -> int:
    """Send outbound email for one prospect.

    By default (production) Cal.com booking is NOT triggered — it waits for a
    real prospect reply to POST /webhooks/email.  Pass --simulate to
    immediately simulate a positive reply and complete the full booking flow
    (eval / smoke-test use only).
    """
    prospects = load_synthetic_prospects()
    key = args.prospect_id
    match = next(
        (p for p in prospects
        if p["id"] == key or p.get("crunchbase_id") == key),
        None,
    )
    if not match:
        print(f"No prospect {args.prospect_id}; options: "
              f"{[p['id'] for p in prospects]}", file=sys.stderr)
        return 1
    orch = Orchestrator()
    result = orch.run_one(match, simulate_reply=args.simulate)
    print(json.dumps(result.__dict__, indent=2, default=str))
    return 0


def _cmd_run_all(args: argparse.Namespace) -> int:
    """Send outbound emails for all prospects (no auto-booking).

    Cal.com booking is NOT triggered automatically.  It fires only when a
    real prospect replies via POST /webhooks/email.
    Pass --simulate to run the full pipeline including simulated replies
    (eval harness / CI use only).
    """
    orch = Orchestrator()
    results = orch.run_all(load_synthetic_prospects(), simulate_reply=args.simulate)
    print(json.dumps([r.__dict__ for r in results], indent=2, default=str))
    return 0


def _cmd_simulate_reply(args: argparse.Namespace) -> int:
    """Fire a synthetic inbound-email-webhook event for a specific prospect.

    Simulates the exact JSON payload that Resend sends to POST /webhooks/email
    when a prospect manually replies, then dispatches it through the registered
    email reply handlers — no real HTTP server or Resend account required.

    Use this to test the reply → Cal.com booking path locally:

      python -m agent.main run-one prospect_002      # send email (no booking)
      python -m agent.main simulate-reply prospect_002  # fire positive reply
                                                        # → Cal.com booked
    """
    from .orchestrator import Orchestrator, load_synthetic_prospects
    from .webhooks import _email_reply_handlers, _unwrap_inbound_payload, _extract_email_address

    prospects = load_synthetic_prospects()
    key = args.prospect_id
    match = next(
        (p for p in prospects if p["id"] == key or p.get("crunchbase_id") == key),
        None,
    )
    if not match:
        print(f"No prospect {key}; options: {[p['id'] for p in prospects]}",
              file=sys.stderr)
        return 1

    # Build the Orchestrator so _reply_lookup and _email_brief are populated,
    # then send the email (without simulate_reply) to register the lookups.
    orch = Orchestrator()
    result = orch.run_one(match, simulate_reply=False)
    print(f"Email sent → message_id={result.email_message_id}  "
          f"(no booking yet)\n")

    # Determine which address to reply from — the actual delivered-to address.
    # When routing to sink, email_res.to is the sink address (e.g.
    # gashawbekelek@gmail.com); we need to fire the webhook with that as sender.
    # _reply_lookup maps sink_addr → prospect_email.  The sink addr is the
    # value of email_res.to, which was registered as the key.  Reverse-lookup:
    sink_addr = None
    for k, v in orch._reply_lookup.items():
        if v == match["contact"]["email"] and k != v:
            sink_addr = k
            break
    from_addr = sink_addr or match["contact"]["email"]

    # Build the synthetic Resend inbound payload
    reply_text = args.text or "Interested — worth 30 minutes."
    synthetic_payload = {
        "type": "email.received",
        "data": {
            "from": from_addr,
            "to": [orch.cfg.reply_to_email or "replies@tenacious.internal"],
            "subject": f"Re: {result.email_message_id}",
            "text": reply_text,
        },
    }

    payload = _unwrap_inbound_payload(synthetic_payload)
    body_text = payload.get("text", "").lower()
    if any(w in body_text for w in (
        "interested", "tell me more", "yes", "sure", "sounds good",
        "let's talk", "love to chat", "worth a call", "30 minutes",
        "schedule", "book", "calendar",
    )):
        kind = "reply_positive"
    else:
        kind = "reply_other"

    print(f"Firing {kind!r} webhook from {from_addr!r} …")
    for handler in _email_reply_handlers:
        try:
            handler(kind=kind, from_addr=from_addr,
                    subject=payload.get("subject", ""), payload=payload)
        except Exception as exc:
            print(f"  handler error: {exc}", file=sys.stderr)

    # Re-check result: if a booking was created it will appear in the
    # HubSpot mock's engagement log.
    print("Done.  Check HubSpot mock + Cal.com mock for booking confirmation.")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:  # pragma: no cover
    import uvicorn  # type: ignore
    uvicorn.run("agent.webhooks:build_app", factory=True,
                host=args.host, port=args.port, reload=False)
    return 0


def _cmd_dry_run(args: argparse.Namespace) -> int:
    """Run all prospects through the pipeline with kill-switch engaged (sink only).

    Clears LLM API keys so the deterministic fallback template is used —
    no API credits consumed, each prospect completes in under 1 s.

    Cal.com booking is NOT triggered (simulate_reply=False).  The dry-run
    verifies the enrich → compose → send → HubSpot path only.
    Pass --simulate to also exercise the reply → booking path.
    """
    import os
    os.environ.pop("OPENROUTER_API_KEY", None)
    os.environ.pop("ANTHROPIC_API_KEY", None)
    os.environ["LLM_TIER"] = "dev"  # fallback path, no Anthropic SDK
    simulate = getattr(args, "simulate", False)
    orch = Orchestrator()
    results = orch.run_all(load_synthetic_prospects(), simulate_reply=simulate)
    for r in results:
        print(json.dumps(r.__dict__, indent=2, default=str))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run all prospects through the pipeline (kill-switch engaged, sink only).",
    )
    sub = parser.add_subparsers(dest="cmd", required=False)

    p_en = sub.add_parser("enrich")
    p_en.add_argument("crunchbase_id")
    p_en.set_defaults(func=_cmd_enrich)

    p_ro = sub.add_parser(
        "run-one",
        help="Send outbound email for one prospect (no auto-booking; use --simulate for eval).",
    )
    p_ro.add_argument("prospect_id")
    p_ro.add_argument(
        "--simulate",
        action="store_true",
        default=False,
        help="Immediately simulate a positive reply and book a slot (eval/test only).",
    )
    p_ro.set_defaults(func=_cmd_run_one)

    p_ra = sub.add_parser(
        "run-all",
        help="Send outbound emails for all prospects (no auto-booking; use --simulate for eval).",
    )
    p_ra.add_argument(
        "--simulate",
        action="store_true",
        default=False,
        help="Immediately simulate positive replies and book slots (eval/test only).",
    )
    p_ra.set_defaults(func=_cmd_run_all)

    p_dr = sub.add_parser(
        "dry-run",
        help="Run all prospects with kill-switch (no LLM cost, no auto-booking).",
    )
    p_dr.add_argument(
        "--simulate",
        action="store_true",
        default=False,
        help="Also simulate replies and booking (eval/test only).",
    )
    p_dr.set_defaults(func=_cmd_dry_run)

    p_sr = sub.add_parser(
        "simulate-reply",
        help="Fire a synthetic reply webhook for one prospect (tests reply→booking path).",
    )
    p_sr.add_argument("prospect_id")
    p_sr.add_argument(
        "--text",
        default="Interested — worth 30 minutes.",
        help="Reply body text (default: positive reply).",
    )
    p_sr.set_defaults(func=_cmd_simulate_reply)

    p_se = sub.add_parser("serve")
    p_se.add_argument("--host", default="0.0.0.0")
    p_se.add_argument("--port", type=int, default=8080)
    p_se.set_defaults(func=_cmd_serve)

    args = parser.parse_args(argv)
    if getattr(args, "dry_run", False):
        return _cmd_dry_run(args)
    if not args.cmd:
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
