"""Top-level enrichment: merge all signals into hiring_signal_brief.

This is the function the agent calls before composing the first outbound.
It runs every sub-signal, assembles per-signal confidence + source + timestamp,
and assigns an ICP segment with confidence and justifications.

Schema
------
The output dict conforms to data/seed/hiring_signal_brief.schema.json.
Every claim in the outreach email must map to a field in this brief.
Fields with confidence < 0.55 must trigger softer phrasing (agent rule).

Key additions over earlier versions:
  - Per-signal source + fetched_at timestamps (data_sources_checked list)
  - Structured velocity_label enum (aligns with schema "insufficient_signal" etc.)
  - ICP-filtered funding via funding.check_funding() — staleness-aware
  - Typed layoff signal via layoffs.check_layoffs_typed() — CSV or fixture
  - honesty_flags list — explicit flags the composer must respect
  - silent_company_warning — set when AI maturity score seems low but signal
    count is also low (quiet-but-sophisticated risk; P-025 sibling)
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import crunchbase, jobposts, leadership
from .ai_maturity import score_ai_maturity
from .competitor_gap import build_competitor_gap_brief
from .funding import check_funding
from .layoffs import check_layoffs_typed
from ..tracing import get_tracer


@dataclass
class SignalRecord:
    """Per-signal provenance: source, timestamp, confidence.

    Stored in data_sources_checked list so every claim is auditable.
    """
    source: str
    status: str          # "success" | "partial" | "no_data" | "error"
    fetched_at: float    # Unix timestamp
    confidence: float
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "source": self.source,
            "status": self.status,
            "fetched_at": datetime.fromtimestamp(self.fetched_at, tz=timezone.utc).isoformat(),
            "confidence": self.confidence,
        }
        if self.error_message:
            d["error_message"] = self.error_message
        return d


def build_hiring_signal_brief(crunchbase_id: str) -> dict[str, Any]:
    """Build the hiring-signal brief and return it as a plain dict.

    Output conforms to data/seed/hiring_signal_brief.schema.json.
    Includes per-signal source, fetched_at, confidence, velocity_label,
    honesty_flags, and silent_company_warning.
    """
    tracer = get_tracer()
    with tracer.trace("enrichment.hiring_signal_brief", crunchbase_id=crunchbase_id) as attrs:
        firmographics = crunchbase.lookup(crunchbase_id)
        if firmographics is None:
            return {"error": "unknown_crunchbase_id", "crunchbase_id": crunchbase_id}

        now = time.time()
        data_sources: list[SignalRecord] = []

        # --- Funding (ICP-filtered, staleness-aware) ---
        funding_signal = check_funding(crunchbase_id)
        data_sources.append(SignalRecord(
            source="crunchbase_odm_sample",
            status="success" if funding_signal.detected else "no_data",
            fetched_at=funding_signal.fetched_at,
            confidence=funding_signal.confidence,
        ))

        # --- Job velocity (with real 60d delta when live scrape available) ---
        jv = jobposts.job_velocity(crunchbase_id)
        jv_confidence = jobposts.confidence_from_velocity(jv)
        jv_source = (jv or {}).get("sources", ["fixture"])
        data_sources.append(SignalRecord(
            source=jv_source[0] if jv_source else "fixture",
            status="success" if jv else "no_data",
            fetched_at=now,
            confidence=jv_confidence,
        ))

        # --- Layoffs (CSV-backed with fixture fallback) ---
        lf_typed = check_layoffs_typed(crunchbase_id)
        lf = lf_typed.to_legacy_dict()  # legacy shape for segment classifier
        data_sources.append(SignalRecord(
            source=lf_typed.source,
            status="success" if lf_typed.detected else "no_data",
            fetched_at=lf_typed.fetched_at,
            confidence=lf_typed.confidence,
        ))

        # --- Leadership change ---
        ld = leadership.leadership_change(crunchbase_id)
        ld_confidence = 0.9 if ld and ld.get("within_window") else 0.0
        data_sources.append(SignalRecord(
            source="linkedin_public_leadership",
            status="success" if ld else "no_data",
            fetched_at=now,
            confidence=ld_confidence,
        ))

        # --- AI maturity ---
        ai = score_ai_maturity(crunchbase_id)
        ai_confidence = ai.confidence if ai else 0.0
        data_sources.append(SignalRecord(
            source="ai_maturity_public_signals",
            status="success" if ai else "no_data",
            fetched_at=now,
            confidence=ai_confidence,
        ))

        # --- Segment classification ---
        segment_assignment = classify_segment(firmographics, jv, lf, ld, ai)

        # --- Honesty flags (explicit list the composer must respect) ---
        honesty_flags = _compute_honesty_flags(
            funding_signal=funding_signal,
            jv=jv,
            jv_confidence=jv_confidence,
            lf=lf,
            ld=ld,
            ai=ai,
            segment=segment_assignment,
        )

        # --- Silent-company warning ---
        # A low AI maturity score with a low signal count may mean the company
        # is quiet-but-sophisticated rather than genuinely behind. Flag it so
        # the composer uses "ask rather than assert" framing.
        silent_company_warning = (
            ai is not None
            and ai.score <= 1
            and ai.inputs_present <= 2
        )

        brief = {
            "crunchbase_id": crunchbase_id,
            "company_name": firmographics["company_name"],
            "sector": firmographics["sector"],
            "employee_count": firmographics["employee_count"],
            "last_enriched_at": now,
            # Structured velocity (schema-aligned)
            "hiring_velocity": _build_velocity_block(jv, jv_confidence),
            "signals": {
                "funding": funding_signal.to_dict(),
                "job_velocity": jv,
                "layoffs_120d": lf,
                "leadership_change_90d": ld,
                "ai_maturity": (
                    {
                        "score": ai.score,
                        "confidence": ai.confidence,
                        "justifications": ai.justifications,
                        "inputs_present": ai.inputs_present,
                        "high_weight_inputs_present": ai.high_weight_inputs_present,
                    }
                    if ai else None
                ),
            },
            "confidence_per_signal": {
                "funding": funding_signal.confidence,
                "job_velocity": jv_confidence,
                "layoffs_120d": lf_typed.confidence,
                "leadership_change_90d": ld_confidence,
                "ai_maturity": ai_confidence,
            },
            "segment_assignment": segment_assignment,
            "data_sources_checked": [s.to_dict() for s in data_sources],
            "honesty_flags": honesty_flags,
            "silent_company_warning": silent_company_warning,
            # Recommended stack for bench matching (inferred from job roles)
            "recommended_stack": _infer_stack(jv, ai),
        }
        attrs["segment"] = segment_assignment["segment"]
        attrs["segment_confidence"] = segment_assignment["confidence"]
        attrs["honesty_flags"] = honesty_flags
        return brief


def _build_velocity_block(
    jv: dict[str, Any] | None, confidence: float
) -> dict[str, Any]:
    """Build the schema-aligned hiring_velocity block."""
    if not jv:
        return {
            "open_roles_today": 0,
            "open_roles_60_days_ago": None,
            "velocity_label": "insufficient_signal",
            "signal_confidence": 0.0,
            "sources": [],
        }
    total = jv.get("total", 0)
    delta = jv.get("delta_60d")  # None means no snapshot yet
    prior = (total - delta) if delta is not None else None
    return {
        "open_roles_today": total,
        "open_roles_60_days_ago": prior,
        "velocity_label": jv.get("velocity_label", "insufficient_signal"),
        "signal_confidence": confidence,
        "sources": jv.get("sources", []),
    }


def _compute_honesty_flags(
    *,
    funding_signal: Any,
    jv: dict[str, Any] | None,
    jv_confidence: float,
    lf: dict[str, Any] | None,
    ld: dict[str, Any] | None,
    ai: Any,
    segment: dict[str, Any],
) -> list[str]:
    """Produce explicit honesty flags the email composer must respect."""
    flags: list[str] = []

    if jv_confidence < 0.55:
        flags.append("weak_hiring_velocity_signal")

    if ai and ai.confidence < 0.55:
        flags.append("weak_ai_maturity_signal")

    # Conflicting signals: funding present but layoff also present
    if funding_signal.detected and lf and lf.get("within_window"):
        flags.append("conflicting_segment_signals")
        flags.append("layoff_overrides_funding")

    # Funding staleness warning surfaced from FundingSignal
    if funding_signal.staleness_flag and funding_signal.confidence < 0.55:
        if "weak_hiring_velocity_signal" not in flags:
            flags.append("weak_hiring_velocity_signal")

    return list(dict.fromkeys(flags))  # deduplicate, preserve order


def _infer_stack(jv: dict[str, Any] | None, ai: Any) -> str:
    """Infer primary stack from job velocity signals."""
    if not jv:
        return "python"
    ml_roles = jv.get("ml", 0)
    py_roles = jv.get("python", 0)
    data_roles = jv.get("data", 0)
    if ml_roles > 0:
        return "ml"
    if data_roles >= py_roles:
        return "data"
    return "python"


def classify_segment(
    firmographics: dict[str, Any],
    jv: dict[str, Any] | None,
    lf: dict[str, Any] | None,
    ld: dict[str, Any] | None,
    ai,
) -> dict[str, Any]:
    """Assign one of the four ICP segments with confidence and reason.

    Priority (per ICP definition mutual-exclusion rule):
      3 (leadership) > 2 (restructuring) > 4 (capability) > 1 (funded)
    """
    funding = firmographics.get("funding")
    emp = firmographics.get("employee_count", 0)
    total_roles = (jv or {}).get("total", 0)

    # Segment 3: leadership transition
    if ld and ld.get("within_window") and not ld.get("interim"):
        return {
            "segment": 3,
            "name": "engineering_leadership_transition",
            "confidence": 0.9,
            "reason": f"{ld['role']} appointed {ld['days_ago']} days ago",
        }

    # Segment 2: restructuring
    if lf and lf.get("within_window") and emp >= 200:
        return {
            "segment": 2,
            "name": "mid_market_restructuring",
            "confidence": 0.88,
            "reason": f"layoff of {lf['headcount']} ({lf['percent']:.0%}) {lf['days_ago']} days ago; {emp} employees",
        }

    # Segment 4: capability gap (gated on AI maturity >= 2)
    if ai and ai.gates_segment_4() and total_roles >= 3:
        return {
            "segment": 4,
            "name": "specialized_capability_gap",
            "confidence": 0.7 * ai.confidence + 0.3,
            "reason": f"AI maturity {ai.score}/3, {total_roles} open engineering roles",
        }

    # Segment 1: recently funded — uses ICP-filtered funding signal
    if funding and isinstance(funding, dict):
        # Accept both legacy (raw round/amount) and new FundingSignal.to_dict() shapes
        funding_round = funding.get("round")
        amount = funding.get("amount_usd", 0)
        announced_on = funding.get("announced_on")
        if 5_000_000 <= amount <= 30_000_000 and funding_round in {"Series A", "Series B"}:
            return {
                "segment": 1,
                "name": "recently_funded_series_ab",
                "confidence": 0.9 if total_roles >= 3 else 0.55,
                "reason": f"{funding_round} of ${amount:,} on {announced_on}; {total_roles} open eng roles",
            }

    return {
        "segment": None,
        "name": "unassigned",
        "confidence": 0.3,
        "reason": "no strong segment signal; route to generic exploratory email",
    }


def dump_brief(brief: dict[str, Any], path: str | Path) -> None:
    Path(path).write_text(json.dumps(brief, indent=2, default=str), encoding="utf-8")
