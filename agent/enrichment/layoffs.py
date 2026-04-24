"""layoffs.fyi signal with real CSV parsing.

Production path:
  1. Call _fetch_layoffs_csv(url) — HTTP GET the CC-BY CSV, parse, cache in memory.
  2. Call check_layoffs(crunchbase_id) — look up company name in the parsed CSV.
  3. Falls back to synthetic fixture when the CSV is unreachable or unparseable.

layoffs.fyi CSV format (as of 2026-04; CC-BY licensed):
  Company, Location, Industry, Total_Laid_Off, Date, Source, Funds_Raised_Millions, Stage, ...

Production CSV download URL: configure via LAYOFFS_FYI_CSV_URL env var or pass directly.
Typical source: https://layoffs.fyi/ → "Download CSV" link (Google Sheets export).
"""
from __future__ import annotations

import csv
import io
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from .crunchbase import _load_sample
from ..tracing import get_tracer


logger = logging.getLogger(__name__)

# In-memory cache of parsed CSV rows keyed by company name (lower-case)
_CSV_CACHE: dict[str, list[dict[str, str]]] | None = None
_CSV_CACHE_AT: float = 0.0
_CSV_CACHE_TTL = 86_400  # 24 hours


@dataclass
class LayoffSignal:
    """Typed layoff signal with source and freshness metadata.

    Fields
    ------
    detected        : True if a layoff record was found within the window
    event_date      : ISO-8601 date of the layoff event
    headcount       : Number of employees laid off (0 if not reported)
    percent         : Fraction of workforce affected (0.0–1.0; 0 if not reported)
    days_ago        : Days since the event (None if date unparseable)
    within_window   : True if days_ago <= window_days
    source          : "layoffs_fyi_csv" | "fixture" | "not_found"
    fetched_at      : Unix timestamp when this signal was retrieved
    confidence      : 0.85 if within_window else 0.0
    """
    detected: bool
    event_date: str | None
    headcount: int
    percent: float
    days_ago: int | None
    within_window: bool
    source: str
    fetched_at: float
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "detected": self.detected,
            "date": self.event_date,
            "headcount": self.headcount,
            "percent": self.percent,
            "days_ago": self.days_ago,
            "within_window": self.within_window,
            "source": self.source,
            "fetched_at": self.fetched_at,
            "confidence": self.confidence,
        }

    def to_legacy_dict(self) -> dict[str, Any] | None:
        """Return the legacy dict shape consumed by brief_generator, or None."""
        if not self.detected:
            return None
        return {
            "date": self.event_date,
            "headcount": self.headcount,
            "percent": self.percent,
            "days_ago": self.days_ago,
            "source": "layoffs.fyi",
            "within_window": self.within_window,
        }


def _parse_layoffs_csv_row(row: dict[str, str]) -> dict[str, Any] | None:
    """Parse one row of the layoffs.fyi CSV into a normalised dict.

    Expected columns (case-insensitive, extra columns ignored):
      Company, Total_Laid_Off, Date, Percentage

    Returns None for rows with missing or unparseable required fields.
    """
    company = row.get("Company", row.get("company", "")).strip()
    if not company:
        return None

    total_str = row.get("Total_Laid_Off", row.get("total_laid_off", "")).strip()
    date_str = row.get("Date", row.get("date", "")).strip()
    pct_str = row.get("Percentage", row.get("percentage", "")).strip()

    if not date_str:
        return None

    # Parse headcount (may be empty — layoffs.fyi sometimes omits it)
    headcount = 0
    try:
        headcount = int(total_str.replace(",", "")) if total_str else 0
    except ValueError:
        pass

    # Parse percentage (stored as "0.15" or "15%" — normalise to 0.0–1.0)
    percent = 0.0
    try:
        if pct_str.endswith("%"):
            percent = float(pct_str[:-1]) / 100.0
        elif pct_str:
            val = float(pct_str)
            percent = val / 100.0 if val > 1.0 else val
    except ValueError:
        pass

    return {"company": company, "date": date_str, "headcount": headcount, "percent": percent}


def _fetch_layoffs_csv(url: str) -> dict[str, list[dict[str, Any]]]:
    """Fetch and parse the layoffs.fyi CC-BY CSV.

    Returns a dict keyed by lower-cased company name → list of event dicts.
    Raises on HTTP or parse failure (caller falls back to fixture).
    """
    import urllib.request

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "TenaciousBot/1.0 (+https://tenacious.consulting/bot)"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read().decode("utf-8", errors="replace")

    reader = csv.DictReader(io.StringIO(raw))
    index: dict[str, list[dict[str, Any]]] = {}
    for row in reader:
        parsed = _parse_layoffs_csv_row(dict(row))
        if parsed is None:
            continue
        key = parsed["company"].lower()
        index.setdefault(key, []).append(parsed)
    return index


def _get_csv_cache(url: str | None) -> dict[str, list[dict[str, Any]]] | None:
    """Return the CSV index, fetching and caching if stale. Returns None on failure."""
    global _CSV_CACHE, _CSV_CACHE_AT
    if url is None:
        return None
    now = time.time()
    if _CSV_CACHE is not None and (now - _CSV_CACHE_AT) < _CSV_CACHE_TTL:
        return _CSV_CACHE
    try:
        _CSV_CACHE = _fetch_layoffs_csv(url)
        _CSV_CACHE_AT = now
        return _CSV_CACHE
    except Exception as exc:  # noqa: BLE001
        logger.debug("layoffs.fyi CSV fetch failed (%s); falling back to fixture", exc)
        return None


def _lookup_csv(
    company_name: str,
    csv_index: dict[str, list[dict[str, Any]]],
    window_days: int,
) -> LayoffSignal | None:
    """Search parsed CSV index for a layoff event within window_days."""
    now = time.time()
    events = csv_index.get(company_name.lower(), [])
    best: dict[str, Any] | None = None
    best_days: int | None = None

    for event in events:
        days_ago = _days_ago(event["date"])
        if days_ago is None:
            continue
        if days_ago <= window_days:
            if best_days is None or days_ago < best_days:
                best = event
                best_days = days_ago

    if best is None:
        return None

    return LayoffSignal(
        detected=True,
        event_date=best["date"],
        headcount=best["headcount"],
        percent=best["percent"],
        days_ago=best_days,
        within_window=True,
        source="layoffs_fyi_csv",
        fetched_at=now,
        confidence=0.85,
    )


def check_layoffs(
    crunchbase_id: str,
    window_days: int = 120,
    csv_url: str | None = None,
) -> dict[str, Any] | None:
    """Return layoff signal dict (legacy shape) or None.

    Tries csv_url first if provided; falls back to synthetic fixture.
    For typed output, use check_layoffs_typed().
    """
    signal = check_layoffs_typed(crunchbase_id, window_days=window_days, csv_url=csv_url)
    return signal.to_legacy_dict()


def check_layoffs_typed(
    crunchbase_id: str,
    window_days: int = 120,
    csv_url: str | None = None,
) -> LayoffSignal:
    """Return a fully-typed LayoffSignal. Always returns (never None).

    Resolution order:
      1. layoffs.fyi CC-BY CSV (if csv_url provided and reachable)
      2. Synthetic fixture (production fallback / dev path)
    """
    tracer = get_tracer()
    with tracer.trace("layoffs.check", crunchbase_id=crunchbase_id, window_days=window_days) as attrs:
        now = time.time()
        rec = _load_sample().get(crunchbase_id)
        company_name = (rec or {}).get("company_name", "")

        # Path 1: real CSV
        csv_index = _get_csv_cache(csv_url)
        if csv_index is not None and company_name:
            signal = _lookup_csv(company_name, csv_index, window_days)
            if signal is not None:
                attrs["source"] = "layoffs_fyi_csv"
                attrs["found"] = True
                return signal
            # CSV loaded but no match — return clean not-found from CSV
            attrs["source"] = "layoffs_fyi_csv"
            attrs["found"] = False
            return LayoffSignal(
                detected=False, event_date=None, headcount=0, percent=0.0,
                days_ago=None, within_window=False,
                source="layoffs_fyi_csv", fetched_at=now, confidence=0.0,
            )

        # Path 2: fixture fallback
        attrs["source"] = "fixture"
        if not rec:
            attrs["found"] = False
            return LayoffSignal(
                detected=False, event_date=None, headcount=0, percent=0.0,
                days_ago=None, within_window=False,
                source="not_found", fetched_at=now, confidence=0.0,
            )

        layoff = rec["signals"].get("layoffs_120d")
        attrs["found"] = layoff is not None
        if layoff is None:
            return LayoffSignal(
                detected=False, event_date=None, headcount=0, percent=0.0,
                days_ago=None, within_window=False,
                source="fixture", fetched_at=now, confidence=0.0,
            )

        days = _days_ago(layoff["date"])
        within = days is not None and days <= window_days
        return LayoffSignal(
            detected=True,
            event_date=layoff["date"],
            headcount=layoff["headcount"],
            percent=layoff["percent"],
            days_ago=days,
            within_window=within,
            source="fixture",
            fetched_at=now,
            confidence=0.85 if within else 0.0,
        )


def _days_ago(value: str) -> int | None:
    try:
        return (date.today() - datetime.strptime(value, "%Y-%m-%d").date()).days
    except Exception:
        return None
