"""Run the Act I baseline.

Usage:
  python eval/run_baseline.py               # mock mode (interim default)
  python eval/run_baseline.py --real        # real τ²-Bench + OpenRouter

Writes to eval/score_log.json and eval/traces/trace_log.jsonl.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make `agent` importable when running from repo root
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.tau2_harness import run_pass_at_1  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--slice", default="dev", choices=["dev", "held_out"])
    p.add_argument("--trials", type=int, default=5)
    p.add_argument("--real", action="store_true")
    args = p.parse_args()

    result = run_pass_at_1(
        slice_name=args.slice,
        trials=args.trials,
        real_run=args.real,
    )
    print(
        json.dumps(
            {
                "run_id": result.run_id,
                "slice": result.slice_name,
                "trials": result.trials,
                "tasks": result.tasks,
                "mean_pass_at_1": result.mean(),
                "ci95": result.ci95(),
                "cost_usd_total": result.cost_usd_total,
                "latency_p50_ms": result.latency_ms_p50,
                "latency_p95_ms": result.latency_ms_p95,
                "notes": result.notes,
            },
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
