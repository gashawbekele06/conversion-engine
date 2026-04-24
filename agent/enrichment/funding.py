"""Crunchbase funding-filter signal.

Applies ICP-relevant filtering to the raw Crunchbase funding record:
  - round must be Series A or Series B
  - amount must be in the $5M–$30M range (Tenacious sweet spot)
  - announcement must be within the freshness window (default: 180 days)

Confidence degrades with staleness:
  - ≤90 days  → 0.95  (fresh)
  - 91–180 days → 0.70  (stale, still relevant)
  - >180 days  → 0.35  (very stale; P-025 failure mode)

Production: replaces the raw passthrough in crunchbase.lookup() with this
module so every consumer gets freshness-checked, ICP-filtered funding data.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from .crunchbase import _load_sample
from ..tracing import get_tracer


# ICP constraints from icp_definition.md — Segment 1 qualifying range
ICP_ROUNDS = {"Series A", "Series B"}
ICP_MIN_USD = 5_000_000
ICP_MAX_USD = 30_000_000

# Staleness thresholds (days since announced_on)
FRESH_THRESHOLD_DAYS = 90
STALE_THRESHOLD_DAYS = 180


@dataclass
class FundingSignal:
    """Typed funding signal with ICP filter and freshness metadata.

    Fields
    ------
    detected        : True if a qualifying funding record was found
    round           : Funding round label ("Series A", "Series B", etc.)
    amount_usd      : Round size in US dollars
    announced_on    : ISO-8601 date string of the announcement
    days_since      : Days elapsed since announced_on (None if unparseable)
    icp_eligible    : True if round + amount match Segment 1 criteria
    confidence      : 0.0–1.0; degrades with staleness (see module docstring)
    staleness_flag  : Human-readable warning if data is old or ICP-ineligible
    source          : Data source identifier
    fetched_at      : Unix timestamp when this record was retrieved
    """
    detected: bool
    round: str | None
    amount_usd: int | None
    announced_on: str | None
    days_since: int | None
    icp_eligible: bool
    confidence: float
    staleness_flag: str | None
    source: str
    fetched_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "detected": self.detected,
            "round": self.round,
            "amount_usd": self.amount_usd,
            "announced_on": self.announced_on,
            "days_since": self.days_since,
            "icp_eligible": self.icp_eligible,
            "confidence": self.confidence,
            "staleness_flag": self.staleness_flag,
            "source": self.source,
            "fetched_at": self.fetched_at,
        }


def check_funding(crunchbase_id: str) -> FundingSignal:
    """Return a freshness-checked, ICP-filtered funding signal.

    Always returns a FundingSignal (never None). When no funding record
    exists, detected=False and confidence=0.0.
    """
    tracer = get_tracer()
    with tracer.trace("funding.check", crunchbase_id=crunchbase_id) as attrs:
        now = time.time()
        rec = _load_sample().get(crunchbase_id)
        if not rec:
            attrs["found"] = False
            return FundingSignal(
                detected=False, round=None, amount_usd=None, announced_on=None,
                days_since=None, icp_eligible=False, confidence=0.0,
                staleness_flag="company record not found",
                source="crunchbase_odm_sample", fetched_at=now,
            )

        raw = rec["signals"].get("funding")
        if not raw:
            attrs["found"] = False
            return FundingSignal(
                detected=False, round=None, amount_usd=None, announced_on=None,
                days_since=None, icp_eligible=False, confidence=0.0,
                staleness_flag=None, source="crunchbase_odm_sample", fetched_at=now,
            )

        attrs["found"] = True
        funding_round = raw.get("round")
        amount = raw.get("amount_usd", 0)
        announced_on = raw.get("announced_on")

        # Compute days since announcement
        days_since = _days_since(announced_on)

        # ICP eligibility: right round + right size
        icp_eligible = (
            funding_round in ICP_ROUNDS
            and ICP_MIN_USD <= amount <= ICP_MAX_USD
        )

        # Confidence degrades with staleness (P-025 mitigation)
        confidence, staleness_flag = _confidence_from_staleness(days_since, icp_eligible)

        attrs["icp_eligible"] = icp_eligible
        attrs["days_since"] = days_since
        attrs["confidence"] = confidence

        return FundingSignal(
            detected=True,
            round=funding_round,
            amount_usd=amount,
            announced_on=announced_on,
            days_since=days_since,
            icp_eligible=icp_eligible,
            confidence=confidence,
            staleness_flag=staleness_flag,
            source="crunchbase_odm_sample",
            fetched_at=now,
        )


def _days_since(announced_on: str | None) -> int | None:
    if not announced_on:
        return None
    try:
        event_date = datetime.strptime(announced_on, "%Y-%m-%d").date()
        return (date.today() - event_date).days
    except Exception:
        return None


def _confidence_from_staleness(
    days_since: int | None, icp_eligible: bool
) -> tuple[float, str | None]:
    """Return (confidence, staleness_flag) based on days elapsed."""
    if not icp_eligible:
        return 0.0, "round or amount outside ICP Segment 1 criteria"
    if days_since is None:
        return 0.5, "announced_on date unparseable — staleness unknown"
    if days_since <= FRESH_THRESHOLD_DAYS:
        return 0.95, None
    if days_since <= STALE_THRESHOLD_DAYS:
        return 0.70, f"funding announced {days_since} days ago — moderately stale"
    # >180 days: P-025 failure mode — very stale, confidence drops sharply
    return 0.35, (
        f"funding announced {days_since} days ago — very stale (P-025). "
        "Use hedged language: 'per public records from earlier this year'."
    )
