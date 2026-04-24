"""Bench-gated commitment helpers.

The agent MUST never commit to capacity that `bench_summary.json` does
not show. This module exposes the one function every outbound-composer
and every scheduling step should call before making a commitment.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import load_config
from .tracing import get_tracer


def _load_summary() -> dict[str, Any]:
    cfg = load_config()
    return json.loads((cfg.seed_dir / "bench_summary.json").read_text(encoding="utf-8"))


def capacity_for(stack: str) -> dict[str, Any]:
    """Return capacity record for a stack slug; empty dict if unknown."""
    tracer = get_tracer()
    with tracer.trace("bench.capacity_for", stack=stack) as attrs:
        summary = _load_summary()
        cap = summary.get("stacks", summary.get("capabilities", {})).get(stack, {})
        attrs["available"] = cap.get("available_engineers", 0)
        return cap


def can_commit(stack: str, engineers_requested: int,
               start_in_days: int | None = None) -> tuple[bool, str]:
    """Return (can_commit, reason)."""
    summary = _load_summary()
    cap = summary.get("stacks", summary.get("capabilities", {})).get(stack, {})
    if not cap:
        return False, f"unknown_stack:{stack}"
    available = cap.get("available_engineers", 0)
    if engineers_requested > available:
        return False, (f"requested {engineers_requested} but bench shows "
                       f"{available} available; must escalate to human")
    constraints = summary.get("hard_constraints", {})
    max_start = constraints.get("max_simultaneous_starts_per_week", 3)
    min_days = constraints.get("earliest_start_date_days_out", 7)
    if engineers_requested > max_start:
        return False, (f"requested {engineers_requested} simultaneous starts exceeds "
                       f"weekly maximum of {max_start}")
    if start_in_days is not None and start_in_days < min_days:
        return False, f"requested start in {start_in_days}d < minimum {min_days}d"
    return True, "ok"
