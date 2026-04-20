"""layoffs.fyi signal.

Production: download the CC-BY CSV at startup or weekly; parse by company.
Interim: return the layoff record attached to the synthetic fixture.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .crunchbase import _load_sample
from ..tracing import get_tracer


def check_layoffs(crunchbase_id: str, window_days: int = 120) -> dict[str, Any] | None:
    tracer = get_tracer()
    with tracer.trace("layoffs.check", crunchbase_id=crunchbase_id, window_days=window_days) as attrs:
        rec = _load_sample().get(crunchbase_id)
        if not rec:
            attrs["found"] = False
            return None
        layoff = rec["signals"].get("layoffs_120d")
        attrs["found"] = layoff is not None
        if layoff is None:
            return None
        event_date = _parse_date(layoff["date"])
        days_ago = (date.today() - event_date).days if event_date else None
        return {
            "date": layoff["date"],
            "headcount": layoff["headcount"],
            "percent": layoff["percent"],
            "days_ago": days_ago,
            "source": "layoffs.fyi",
            "within_window": days_ago is not None and days_ago <= window_days,
        }


def _parse_date(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return None
