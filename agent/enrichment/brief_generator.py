"""Top-level enrichment: merge all signals into hiring_signal_brief.json.

This is the function the agent calls before composing the first outbound.
It runs every sub-signal, assembles per-signal confidence, and assigns
an ICP segment with confidence and justifications.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from . import crunchbase, jobposts, layoffs, leadership
from .ai_maturity import score_ai_maturity
from .competitor_gap import build_competitor_gap_brief
from ..tracing import get_tracer


def build_hiring_signal_brief(crunchbase_id: str) -> dict[str, Any]:
    tracer = get_tracer()
    with tracer.trace("enrichment.hiring_signal_brief", crunchbase_id=crunchbase_id) as attrs:
        firmographics = crunchbase.lookup(crunchbase_id)
        if firmographics is None:
            return {"error": "unknown_crunchbase_id", "crunchbase_id": crunchbase_id}

        jv = jobposts.job_velocity(crunchbase_id)
        lf = layoffs.check_layoffs(crunchbase_id)
        ld = leadership.leadership_change(crunchbase_id)
        ai = score_ai_maturity(crunchbase_id)

        segment_assignment = classify_segment(firmographics, jv, lf, ld, ai)

        brief = {
            "crunchbase_id": crunchbase_id,
            "company_name": firmographics["company_name"],
            "sector": firmographics["sector"],
            "employee_count": firmographics["employee_count"],
            "last_enriched_at": time.time(),
            "signals": {
                "funding": firmographics.get("funding"),
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
                    if ai
                    else None
                ),
            },
            "confidence_per_signal": {
                "funding": 0.95 if firmographics.get("funding") else 0.0,
                "job_velocity": jobposts.confidence_from_velocity(jv),
                "layoffs_120d": 0.85 if lf and lf.get("within_window") else 0.0,
                "leadership_change_90d": 0.9 if ld and ld.get("within_window") else 0.0,
                "ai_maturity": ai.confidence if ai else 0.0,
            },
            "segment_assignment": segment_assignment,
        }
        attrs["segment"] = segment_assignment["segment"]
        attrs["segment_confidence"] = segment_assignment["confidence"]
        return brief


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

    # Segment 1: recently funded
    if funding:
        amount = funding.get("amount_usd", 0)
        if 5_000_000 <= amount <= 30_000_000 and funding.get("round") in {"Series A", "Series B"}:
            return {
                "segment": 1,
                "name": "recently_funded_series_ab",
                "confidence": 0.9 if total_roles >= 3 else 0.55,
                "reason": f"{funding['round']} of ${amount:,} on {funding['announced_on']}; {total_roles} open eng roles",
            }

    return {
        "segment": None,
        "name": "unassigned",
        "confidence": 0.3,
        "reason": "no strong segment signal; route to generic exploratory email",
    }


def dump_brief(brief: dict[str, Any], path: str | Path) -> None:
    Path(path).write_text(json.dumps(brief, indent=2, default=str), encoding="utf-8")
