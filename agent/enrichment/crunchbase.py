"""Crunchbase ODM sample lookup.

In production this hits the downloaded luminati-io/Crunchbase-dataset-samples
JSON. For the interim deliverable we read our synthetic_prospects.json
shim (which mirrors the Crunchbase schema fields we actually use) so the
pipeline is runnable without network access.

Every returned record MUST include `crunchbase_id` and `last_enriched_at`
— the evidence-graph check in Act V verifies these.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ..config import load_config
from ..tracing import get_tracer


_CACHE: dict[str, dict[str, Any]] | None = None


def _load_sample() -> dict[str, dict[str, Any]]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    cfg = load_config()
    path = cfg.seed_dir.parent / "synthetic_prospects.json"
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    _CACHE = {p["crunchbase_id"]: p for p in data["prospects"]}
    return _CACHE


def lookup(crunchbase_id: str) -> dict[str, Any] | None:
    """Return firmographic record by Crunchbase ID, or None if not found."""
    tracer = get_tracer()
    with tracer.trace("crunchbase.lookup", crunchbase_id=crunchbase_id) as attrs:
        sample = _load_sample()
        record = sample.get(crunchbase_id)
        attrs["found"] = record is not None
        if record is None:
            return None
        return {
            "crunchbase_id": crunchbase_id,
            "company_name": record["company_name"],
            "sector": record["sector"],
            "employee_count": record["employee_count"],
            "funding": record["signals"].get("funding"),
            "last_enriched_at": time.time(),
            "source": "crunchbase_odm_sample",
        }


def lookup_by_company_name(name: str) -> dict[str, Any] | None:
    for rec in _load_sample().values():
        if rec["company_name"].lower() == name.lower():
            return lookup(rec["crunchbase_id"])
    return None
