"""Leadership-change signal from Crunchbase records + press releases.

Detects the most recent CTO/VP-Eng/Head-of-Eng appointment within a rolling
window (default 90 days) and returns a typed LeadershipSignal.

Data sources (resolution order):
  1. Crunchbase ODM sample fixture (``data/synthetic_prospects.json``)
  2. Press-release parser (production extension point — not yet wired)

Edge cases handled:
  - No Crunchbase record for the given ID         → LeadershipSignal(detected=False, reason="unknown_crunchbase_id")
  - Record exists but no leadership_change field  → LeadershipSignal(detected=False, reason="no_change_in_record")
  - Appointment date unparseable                  → days_ago=None, within_window=False
  - Interim appointment                           → within_window may be True but interim=True signals caution
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from .crunchbase import _load_sample
from ..tracing import get_tracer


@dataclass
class LeadershipSignal:
    """Typed leadership-change signal with full provenance.

    Fields
    ------
    detected        : True if a qualifying change was found
    role            : Job title of the new leader (e.g. "CTO")
    name            : Person's name when available in source data
    appointment_date: ISO-8601 date string or None
    days_ago        : Days since appointment (None if date unparseable)
    within_window   : True when days_ago <= window_days
    interim         : True if the appointment is marked interim
    source          : Attribution string for the data source
    fetched_at      : Unix timestamp when this signal was retrieved
    confidence      : 0.9 if within_window and not interim,
                      0.5 if interim (lower signal quality),
                      0.0 if not detected
    no_change_reason: Human-readable explanation when detected=False
    """
    detected: bool
    role: str | None
    name: str | None
    appointment_date: str | None
    days_ago: int | None
    within_window: bool
    interim: bool
    source: str
    fetched_at: float
    confidence: float
    no_change_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "detected": self.detected,
            "role": self.role,
            "name": self.name,
            "appointment_date": self.appointment_date,
            "days_ago": self.days_ago,
            "within_window": self.within_window,
            "interim": self.interim,
            "source": self.source,
            "fetched_at": self.fetched_at,
            "confidence": self.confidence,
        }
        if self.no_change_reason:
            d["no_change_reason"] = self.no_change_reason
        return d

    def to_legacy_dict(self) -> dict[str, Any] | None:
        """Return the legacy plain-dict shape consumed by brief_generator, or None."""
        if not self.detected:
            return None
        return {
            "role": self.role,
            "appointment_date": self.appointment_date,
            "days_ago": self.days_ago,
            "within_window": self.within_window,
            "interim": self.interim,
            "source": self.source,
        }


def _not_found(reason: str) -> LeadershipSignal:
    return LeadershipSignal(
        detected=False,
        role=None,
        name=None,
        appointment_date=None,
        days_ago=None,
        within_window=False,
        interim=False,
        source="not_found",
        fetched_at=time.time(),
        confidence=0.0,
        no_change_reason=reason,
    )


def check_leadership_typed(
    crunchbase_id: str,
    window_days: int = 90,
) -> LeadershipSignal:
    """Return a fully-typed LeadershipSignal. Always returns (never None).

    Resolution order:
      1. Crunchbase ODM sample fixture (synthetic_prospects.json)
      2. Production extension: press-release parser (future work)

    Edge cases:
      - Missing Crunchbase record → detected=False, reason="unknown_crunchbase_id"
      - No leadership_change_90d in record → detected=False, reason="no_change_in_record"
      - Unparseable date → within_window=False, days_ago=None
      - Interim appointment → confidence=0.5 (not 0.9)
    """
    tracer = get_tracer()
    with tracer.trace("leadership.check", crunchbase_id=crunchbase_id, window_days=window_days) as attrs:
        now = time.time()
        rec = _load_sample().get(crunchbase_id)

        if not rec:
            attrs["found"] = False
            attrs["reason"] = "unknown_crunchbase_id"
            return _not_found("unknown_crunchbase_id")

        change = rec["signals"].get("leadership_change_90d")
        if change is None:
            attrs["found"] = False
            attrs["reason"] = "no_change_in_record"
            return _not_found("no_change_in_record")

        appt_date = _parse_date(change["appointment_date"])
        days_ago = (date.today() - appt_date).days if appt_date else None
        within = days_ago is not None and days_ago <= window_days
        interim = change.get("interim", False)

        # Confidence: 0.9 for confirmed change in window, 0.5 for interim
        if within and not interim:
            confidence = 0.9
        elif within and interim:
            confidence = 0.5
        else:
            confidence = 0.0

        attrs["found"] = True
        attrs["within_window"] = within
        attrs["interim"] = interim
        attrs["confidence"] = confidence

        return LeadershipSignal(
            detected=True,
            role=change.get("role"),
            name=change.get("name"),
            appointment_date=change["appointment_date"],
            days_ago=days_ago,
            within_window=within,
            interim=interim,
            source=change.get("source", "crunchbase_press"),
            fetched_at=now,
            confidence=confidence,
        )


def leadership_change(crunchbase_id: str, window_days: int = 90) -> dict[str, Any] | None:
    """Return legacy plain-dict or None. Used by brief_generator for segment logic.

    For full typed output use check_leadership_typed().
    """
    return check_leadership_typed(crunchbase_id, window_days=window_days).to_legacy_dict()


def _parse_date(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return None
