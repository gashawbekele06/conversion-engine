"""Leadership-change signal from Crunchbase + press releases.

Returns the most recent CTO/VP-Eng appointment in the last 90 days.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .crunchbase import _load_sample
from ..tracing import get_tracer


def leadership_change(crunchbase_id: str, window_days: int = 90) -> dict[str, Any] | None:
    tracer = get_tracer()
    with tracer.trace("leadership.check", crunchbase_id=crunchbase_id) as attrs:
        rec = _load_sample().get(crunchbase_id)
        if not rec:
            attrs["found"] = False
            return None
        change = rec["signals"].get("leadership_change_90d")
        attrs["found"] = change is not None
        if change is None:
            return None
        appt_date = _parse_date(change["appointment_date"])
        days_ago = (date.today() - appt_date).days if appt_date else None
        return {
            "role": change["role"],
            "appointment_date": change["appointment_date"],
            "days_ago": days_ago,
            "within_window": days_ago is not None and days_ago <= window_days,
            "interim": change.get("interim", False),
            "source": "crunchbase_press",
        }


def _parse_date(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return None
