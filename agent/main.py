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
    brief = build_hiring_signal_brief(args.crunchbase_id)
    gap = build_competitor_gap_brief(args.crunchbase_id)
    print(json.dumps({"brief": brief, "competitor_gap": gap}, indent=2, default=str))
    return 0


def _cmd_run_one(args: argparse.Namespace) -> int:
    prospects = load_synthetic_prospects()
    #match = next((p for p in prospects if p["id"] == args.prospect_id), None)
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
    result = orch.run_one(match, simulate_reply=True)
    print(json.dumps(result.__dict__, indent=2, default=str))
    return 0


def _cmd_run_all(args: argparse.Namespace) -> int:
    orch = Orchestrator()
    results = orch.run_all(load_synthetic_prospects())
    print(json.dumps([r.__dict__ for r in results], indent=2, default=str))
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
    """
    import os
    os.environ.pop("OPENROUTER_API_KEY", None)
    os.environ.pop("ANTHROPIC_API_KEY", None)
    os.environ["LLM_TIER"] = "dev"  # fallback path, no Anthropic SDK
    orch = Orchestrator()
    results = orch.run_all(load_synthetic_prospects())
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

    p_ro = sub.add_parser("run-one")
    p_ro.add_argument("prospect_id")
    p_ro.set_defaults(func=_cmd_run_one)

    p_ra = sub.add_parser("run-all")
    p_ra.set_defaults(func=_cmd_run_all)

    p_se = sub.add_parser("serve")
    p_se.add_argument("--host", default="0.0.0.0")
    p_se.add_argument("--port", type=int, default=8080)
    p_se.set_defaults(func=_cmd_serve)

    args = parser.parse_args(argv)
    if args.dry_run:
        return _cmd_dry_run(args)
    if not args.cmd:
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
