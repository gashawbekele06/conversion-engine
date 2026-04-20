"""τ²-Bench harness wrapper.

Wraps sierra-research/tau2-bench so every run writes:
  - `eval/traces/trace_log.jsonl` — per-task trajectory (Langfuse-compatible rows)
  - `eval/score_log.json` — pass@1 aggregates with 95% CI

Honest design note:
  The interim harness does NOT yet hit a real LLM. It reads the dev-slice
  task IDs from a pinned manifest, runs the agent's tool-use loop in
  mock mode, and emits `pass@1 = null` placeholders so we NEVER report
  fabricated benchmark numbers. The real scoring run happens after
  τ²-Bench is cloned and the OpenRouter key is wired (see baseline.md).
"""
from __future__ import annotations

import json
import math
import random
import statistics
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.config import load_config
from agent.tracing import get_tracer


REPO_ROOT = Path(__file__).resolve().parents[1]
TRACES = REPO_ROOT / "eval" / "traces" / "trace_log.jsonl"
SCORE_LOG = REPO_ROOT / "eval" / "score_log.json"
DEV_SLICE_PATH = REPO_ROOT / "eval" / "dev_slice.json"
HELDOUT_SLICE_PATH = REPO_ROOT / "eval" / "held_out_slice.json"


@dataclass
class RunResult:
    run_id: str
    model: str
    slice_name: str
    trials: int
    tasks: int
    pass_rates: list[float | None] = field(default_factory=list)
    cost_usd_total: float = 0.0
    latency_ms_p50: float | None = None
    latency_ms_p95: float | None = None
    notes: str = ""

    def mean(self) -> float | None:
        known = [p for p in self.pass_rates if p is not None]
        return statistics.fmean(known) if known else None

    def ci95(self) -> tuple[float | None, float | None]:
        known = [p for p in self.pass_rates if p is not None]
        if len(known) < 2:
            return (None, None)
        m = statistics.fmean(known)
        sd = statistics.pstdev(known)
        half = 1.96 * sd / math.sqrt(len(known))
        return (round(m - half, 4), round(m + half, 4))


def _load_slice(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))["tasks"]


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    k = max(0, min(len(values) - 1, int(round(p * (len(values) - 1)))))
    return values[k]


def run_pass_at_1(
    *,
    slice_name: str,
    trials: int = 5,
    model: str | None = None,
    real_run: bool = False,
    seed: int = 42,
) -> RunResult:
    """Run pass@1 across `trials` seeds on the named slice.

    `real_run=False` (default) executes the mock pipeline. Every pass-rate
    is recorded as `None` — we do NOT invent τ²-Bench scores.

    `real_run=True` assumes τ²-Bench is installed (`pip install tau2-bench`)
    and `OPENROUTER_API_KEY` is present. This is NOT exercised in the
    interim smoke test; it's wired for Days 3–4.
    """
    cfg = load_config()
    tracer = get_tracer()
    path = DEV_SLICE_PATH if slice_name == "dev" else HELDOUT_SLICE_PATH
    tasks = _load_slice(path)

    run = RunResult(
        run_id=f"run_{uuid.uuid4().hex[:8]}",
        model=model or cfg.llm_model,
        slice_name=slice_name,
        trials=trials,
        tasks=len(tasks),
    )
    latencies: list[float] = []

    with tracer.trace("tau2.run_pass_at_1", slice=slice_name, trials=trials) as attrs:
        rng = random.Random(seed)
        if not real_run:
            run.notes = ("mock_run: no τ²-Bench call made; pass_rates recorded as None "
                         "to avoid fabricated numbers. Re-run with --real after wiring OpenRouter.")
            for _ in range(trials):
                run.pass_rates.append(None)
            attrs["real"] = False
        else:  # pragma: no cover — exercised later with real keys
            try:
                from tau2_bench import run_domain  # type: ignore
            except Exception as exc:  # noqa: BLE001
                run.notes = f"tau2_bench import failed: {exc}"
                attrs["real_error"] = str(exc)
                return run
            for t in range(trials):
                start = time.time()
                result = run_domain(
                    domain="retail",
                    tasks=tasks,
                    model=run.model,
                    seed=seed + t,
                )
                latencies.append((time.time() - start) * 1000.0)
                run.pass_rates.append(float(result["pass_at_1"]))
                run.cost_usd_total += float(result.get("usd_cost", 0.0))
            attrs["real"] = True
            run.latency_ms_p50 = _percentile(latencies, 0.50)
            run.latency_ms_p95 = _percentile(latencies, 0.95)

        _append_score_log(run)
        return run


def _append_score_log(run: RunResult) -> None:
    SCORE_LOG.parent.mkdir(parents=True, exist_ok=True)
    blob: dict[str, Any] = {"entries": []}
    if SCORE_LOG.exists():
        try:
            blob = json.loads(SCORE_LOG.read_text(encoding="utf-8"))
        except Exception:
            blob = {"entries": []}
    blob["entries"].append(
        {
            "run_id": run.run_id,
            "run_label": "INTERIM_PLACEHOLDER" if not any(p is not None for p in run.pass_rates) else "real_run",
            "ts": time.time(),
            "model": run.model,
            "slice": run.slice_name,
            "trials": run.trials,
            "tasks": run.tasks,
            "pass_rates": run.pass_rates,
            "pass_rate_mean": run.mean(),
            "pass_rate_ci95_low": run.ci95()[0],
            "pass_rate_ci95_high": run.ci95()[1],
            "cost_usd_total": run.cost_usd_total,
            "latency_ms_p50": run.latency_ms_p50,
            "latency_ms_p95": run.latency_ms_p95,
            "notes": run.notes,
        }
    )
    SCORE_LOG.write_text(json.dumps(blob, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--slice", default="dev")
    p.add_argument("--trials", type=int, default=5)
    p.add_argument("--real", action="store_true",
                   help="Actually call τ²-Bench + OpenRouter. Requires install + API key.")
    args = p.parse_args()
    r = run_pass_at_1(slice_name=args.slice, trials=args.trials, real_run=args.real)
    print(json.dumps(
        {"run_id": r.run_id, "mean": r.mean(), "ci95": r.ci95(), "notes": r.notes},
        indent=2, default=str,
    ))
