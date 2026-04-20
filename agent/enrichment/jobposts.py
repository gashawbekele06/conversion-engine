"""Public job-post velocity signal.

Production: Playwright scrape of BuiltIn / Wellfound / LinkedIn company
careers page, frozen April 2026 snapshot OR live crawl (≤200 companies,
respect robots.txt, no login, no captcha bypass).

Interim: read counts from synthetic_prospects.json.
"""
from __future__ import annotations

from typing import Any

from .crunchbase import _load_sample
from ..tracing import get_tracer


def job_velocity(crunchbase_id: str) -> dict[str, Any] | None:
    tracer = get_tracer()
    with tracer.trace("jobposts.velocity", crunchbase_id=crunchbase_id) as attrs:
        rec = _load_sample().get(crunchbase_id)
        if not rec:
            attrs["found"] = False
            return None
        roles = rec["signals"]["open_engineering_roles"]
        attrs["found"] = True
        total = roles["total"]
        delta = roles["delta_60d"]
        tripled = total >= 3 and total >= (total - delta) * 3
        return {
            "total": total,
            "python": roles.get("python", 0),
            "ml": roles.get("ml", 0),
            "data": roles.get("data", 0),
            "delta_60d": delta,
            "tripled_60d": tripled,
            "sources": ["builtin", "wellfound", "linkedin_public"],
        }


def confidence_from_velocity(v: dict[str, Any] | None) -> float:
    """Map raw velocity to a 0–1 confidence we can cite in outbound.

    < 5 open roles is low confidence per the challenge spec ("fewer than
    five open roles — the agent does not claim 'you are scaling aggressively'").
    """
    if not v:
        return 0.0
    total = v["total"]
    if total < 5:
        return 0.25
    if total < 10:
        return 0.55
    return 0.85
