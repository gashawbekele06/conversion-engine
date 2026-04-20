"""Smoke tests — run the interim pipeline end-to-end without credentials."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.enrichment import build_hiring_signal_brief, build_competitor_gap_brief
from agent.orchestrator import Orchestrator, load_synthetic_prospects
from agent.kill_switch import KillSwitch


def test_kill_switch_default_routes_to_sink() -> None:
    ks = KillSwitch()
    r = ks.resolve("email", "priya@nimbusledger.example", synthetic=True)
    assert r.is_sink is True
    assert r.reason == "synthetic_prospect_routes_to_sink"


def test_enrichment_pipeline_runs() -> None:
    brief = build_hiring_signal_brief("cb_sample_001")
    assert brief["company_name"] == "Nimbus Ledger Inc."
    assert "segment_assignment" in brief
    assert brief["signals"]["ai_maturity"]["score"] in {0, 1, 2, 3}
    assert brief["confidence_per_signal"]["funding"] > 0

    gap = build_competitor_gap_brief("cb_sample_001")
    assert gap["crunchbase_id"] == "cb_sample_001"
    assert "gap_practices" in gap


def test_segment_priority_leadership_beats_funded() -> None:
    """Aurelia Health has both Series C and a new CTO → segment 3."""
    brief = build_hiring_signal_brief("cb_sample_042")
    assert brief["segment_assignment"]["segment"] == 3


def test_segment_4_gated_by_ai_maturity() -> None:
    """Orinda AI has AI maturity >= 2 → segment 4."""
    brief = build_hiring_signal_brief("cb_sample_089")
    assert (brief["signals"]["ai_maturity"]["score"] or 0) >= 2
    assert brief["segment_assignment"]["segment"] == 4


def test_layoff_company_is_segment_2() -> None:
    brief = build_hiring_signal_brief("cb_sample_017")
    assert brief["segment_assignment"]["segment"] == 2


def test_end_to_end_orchestrator_run_one() -> None:
    orch = Orchestrator()
    prospects = load_synthetic_prospects()
    result = orch.run_one(prospects[0], simulate_reply=True)
    assert result.is_sink is True
    assert result.email_message_id
    assert result.hubspot_contact_id
    assert result.calcom_booking_id
    # HubSpot mock now has a contact with both crunchbase_id + last_enriched_at
    store = json.loads((ROOT / "eval" / "traces" / "hubspot_mock.json").read_text())
    contact = next(iter(store["contacts"].values()))
    assert "crunchbase_id" in contact["properties"]
    assert "last_enriched_at" in contact["properties"]


def test_trace_log_is_written() -> None:
    orch = Orchestrator()
    prospects = load_synthetic_prospects()
    orch.run_one(prospects[1], simulate_reply=False)
    trace_path = ROOT / "eval" / "traces" / "trace_log.jsonl"
    assert trace_path.exists()
    lines = [l for l in trace_path.read_text().splitlines() if l.strip()]
    assert len(lines) > 0
    # Check at least one enrichment span exists
    assert any("enrichment.hiring_signal_brief" in l for l in lines)
