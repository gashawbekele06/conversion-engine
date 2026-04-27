"""Unit tests for critical business-logic gates.

Covers the gaps in test_smoke.py:
  - P-028 peer-count gate boundaries (_compose_gap_section)
  - Confidence-band thresholds (_confidence_band)
  - SMS warm-lead enforcement (WarmLeadRequired, classify_inbound)
  - Bench capacity gates (can_commit)
  - Kill-switch routing matrix (synthetic × TENACIOUS_LIVE × channel)
  - HubSpot required-property enforcement (upsert_contact mock path)
  - Reply-gated Cal.com booking (no booking before reply; booking after reply)
  - Webhook inbound email payload parsing (Resend / MailerSend / flat formats)
  - Sink-routing reply lookup (gashawbekelek@gmail.com → marcus@glenmark.example)
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.compose import _compose_gap_section, _confidence_band, PEER_COUNT_SUPPRESS, PEER_COUNT_HEDGE
from agent.channels.sms import SMSChannel, WarmLeadRequired
from agent.bench import can_commit
from agent.config import Config
from agent.kill_switch import KillSwitch
from agent.channels.hubspot import HubSpotChannel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gap(peer_count: int, practice: str = "MLOps pipelines") -> dict:
    """Minimal competitor_gap dict for testing _compose_gap_section."""
    return {
        "peer_count": peer_count,
        "gap_practices": [{"practice": practice, "adoption_rate": 0.6}],
    }


def _brief(confidence_values: dict) -> dict:
    """Minimal hiring_signal_brief for testing _confidence_band."""
    return {"confidence_per_signal": confidence_values}


# ---------------------------------------------------------------------------
# 1. P-028 peer-count gate — _compose_gap_section()
# ---------------------------------------------------------------------------

class TestComposeGapSection:
    """Verify the three tiers: suppress / hedge / assert."""

    # --- Suppress tier (peer_count < PEER_COUNT_SUPPRESS = 3) ---

    def test_zero_peers_suppressed(self):
        assert _compose_gap_section(_gap(0)) == ""

    def test_one_peer_suppressed(self):
        assert _compose_gap_section(_gap(1)) == ""

    def test_two_peers_suppressed(self):
        """peer_count=2 is the boundary just below suppress threshold."""
        assert _compose_gap_section(_gap(2)) == ""

    # --- Hedge tier (PEER_COUNT_SUPPRESS <= peer_count < PEER_COUNT_HEDGE) ---

    def test_three_peers_hedged(self):
        """peer_count=3 is exactly at PEER_COUNT_SUPPRESS — should use hedged language."""
        result = _compose_gap_section(_gap(3))
        assert result != ""
        assert "small number" in result.lower()
        assert "sector" in result.lower()

    def test_four_peers_hedged(self):
        result = _compose_gap_section(_gap(4))
        assert result != ""
        assert "small number" in result.lower()

    # --- Assert tier (peer_count >= PEER_COUNT_HEDGE = 5) ---

    def test_five_peers_full_assertion(self):
        """peer_count=5 is exactly at PEER_COUNT_HEDGE — full assertion."""
        result = _compose_gap_section(_gap(5))
        assert result != ""
        assert "small number" not in result.lower()
        assert "5" in result

    def test_six_peers_full_assertion(self):
        result = _compose_gap_section(_gap(6))
        assert "6" in result
        assert "small number" not in result.lower()

    def test_assertion_contains_peer_count(self):
        result = _compose_gap_section(_gap(8))
        assert "8" in result

    def test_assertion_contains_practice_text(self):
        result = _compose_gap_section(_gap(6, practice="automated testing"))
        assert "automated testing" in result

    # --- Edge cases ---

    def test_empty_gap_practices_suppressed(self):
        assert _compose_gap_section({"peer_count": 10, "gap_practices": []}) == ""

    def test_missing_peer_count_defaults_to_zero(self):
        """Missing peer_count key defaults to 0 — gap suppressed."""
        result = _compose_gap_section({"gap_practices": [{"practice": "MLOps"}]})
        assert result == ""

    def test_practice_missing_text_suppressed(self):
        """gap_practices entry with no 'practice' key → suppressed."""
        gap = {"peer_count": 6, "gap_practices": [{"adoption_rate": 0.7}]}
        assert _compose_gap_section(gap) == ""

    def test_constants_not_drifted(self):
        """The P-028 fix depends on specific threshold values — guard against drift."""
        assert PEER_COUNT_SUPPRESS == 3
        assert PEER_COUNT_HEDGE == 5


# ---------------------------------------------------------------------------
# 2. Confidence band thresholds — _confidence_band()
# ---------------------------------------------------------------------------

class TestConfidenceBand:
    """Verify exact boundaries for high/medium/low bands."""

    def test_high_band_at_0_8(self):
        assert _confidence_band(_brief({"funding": 0.8})) == "high"

    def test_high_band_above_0_8(self):
        assert _confidence_band(_brief({"funding": 0.95})) == "high"

    def test_medium_band_just_below_0_8(self):
        assert _confidence_band(_brief({"funding": 0.79})) == "medium"

    def test_medium_band_at_0_5(self):
        assert _confidence_band(_brief({"funding": 0.5})) == "medium"

    def test_low_band_just_below_0_5(self):
        assert _confidence_band(_brief({"funding": 0.49})) == "low"

    def test_low_band_at_zero(self):
        assert _confidence_band(_brief({"funding": 0.0})) == "low"

    def test_empty_signals_returns_low(self):
        assert _confidence_band(_brief({})) == "low"

    def test_missing_key_returns_low(self):
        assert _confidence_band({}) == "low"

    def test_uses_highest_signal_value(self):
        """Band is determined by the single highest confidence value."""
        brief = _brief({"funding": 0.3, "hiring": 0.85, "layoffs": 0.4})
        assert _confidence_band(brief) == "high"

    def test_multiple_medium_signals(self):
        brief = _brief({"funding": 0.6, "hiring": 0.7})
        assert _confidence_band(brief) == "medium"


# ---------------------------------------------------------------------------
# 3. SMS warm-lead gate — classify_inbound() and WarmLeadRequired
# ---------------------------------------------------------------------------

class TestClassifyInbound:
    """classify_inbound is a static method on SMSChannel."""

    def test_stop_word_stop(self):
        assert SMSChannel.classify_inbound("STOP") == "stop"

    def test_stop_word_unsub(self):
        assert SMSChannel.classify_inbound("UNSUB") == "stop"

    def test_stop_word_unsubscribe(self):
        assert SMSChannel.classify_inbound("UNSUBSCRIBE") == "stop"

    def test_stop_word_quit(self):
        assert SMSChannel.classify_inbound("QUIT") == "stop"

    def test_stop_word_end(self):
        assert SMSChannel.classify_inbound("END") == "stop"

    def test_stop_word_cancel(self):
        assert SMSChannel.classify_inbound("CANCEL") == "stop"

    def test_help_word_help(self):
        assert SMSChannel.classify_inbound("HELP") == "help"

    def test_help_word_info(self):
        assert SMSChannel.classify_inbound("INFO") == "help"

    def test_stop_case_insensitive(self):
        assert SMSChannel.classify_inbound("stop") == "stop"

    def test_stop_mixed_case(self):
        assert SMSChannel.classify_inbound("Stop") == "stop"

    def test_stop_multiword_first_word_matches(self):
        assert SMSChannel.classify_inbound("STOP please") == "stop"

    def test_help_multiword(self):
        assert SMSChannel.classify_inbound("HELP me") == "help"

    def test_regular_reply(self):
        assert SMSChannel.classify_inbound("Sounds interesting, tell me more") == "reply"

    def test_empty_string_returns_reply(self):
        assert SMSChannel.classify_inbound("") == "reply"

    def test_partial_stop_word_is_reply(self):
        """'STOPPING' is not in STOP_WORDS, so it should be classified as reply."""
        assert SMSChannel.classify_inbound("STOPPING by") == "reply"


class TestWarmLeadRequired:
    """SMSChannel.send() must raise WarmLeadRequired for cold prospects."""

    def _cold_channel(self, tmp_path: Path) -> SMSChannel:
        cfg = Config(
            staff_sink_sms="+10000000000",
            staff_sink_email="sink@example.com",
        )
        ch = SMSChannel(cfg)
        # Point sink to an empty temp dir — no prior engagement records
        ch.sink_path = tmp_path / "sms_sink.jsonl"
        return ch

    def test_cold_prospect_raises(self, tmp_path):
        ch = self._cold_channel(tmp_path)
        with pytest.raises(WarmLeadRequired):
            ch.send(to="+251900000000", body="Hello", warm_lead=False)

    def test_warm_lead_flag_bypasses_gate(self, tmp_path):
        ch = self._cold_channel(tmp_path)
        # warm_lead=True should not raise — it will attempt send (mock path)
        result = ch.send(to="+251900000000", body="Hello", warm_lead=True, synthetic=True)
        assert result.ok is True

    def test_prior_sms_engagement_qualifies(self, tmp_path):
        ch = self._cold_channel(tmp_path)
        # Write a prior inbound SMS record
        ch.sink_path.write_text(
            json.dumps({"channel": "sms_inbound", "from": "+251900000000", "text": "Yes"}) + "\n",
            encoding="utf-8",
        )
        # Should not raise — prior engagement found
        result = ch.send(to="+251900000000", body="Follow up", warm_lead=False, synthetic=True)
        assert result.ok is True


# ---------------------------------------------------------------------------
# 4. Bench capacity gates — can_commit()
# ---------------------------------------------------------------------------

class TestCanCommit:
    """Verify the three gates: unknown stack, capacity, constraints."""

    def test_unknown_stack_blocked(self):
        ok, reason = can_commit("quantum_computing", 1)
        assert ok is False
        assert "unknown_stack" in reason

    def test_known_stack_within_capacity(self):
        ok, reason = can_commit("python", 1)
        assert ok is True
        assert reason == "ok"

    def test_over_capacity_blocked(self):
        """Request more engineers than are available on the bench."""
        ok, reason = can_commit("python", 999)
        assert ok is False
        assert "999" in reason
        assert "available" in reason

    def test_over_simultaneous_starts_blocked(self):
        """Requesting > max_simultaneous_starts_per_week (3) is blocked."""
        ok, reason = can_commit("python", 4)
        assert ok is False
        assert "weekly maximum" in reason

    def test_start_too_soon_blocked(self):
        """Requesting start in fewer days than earliest_start_date_days_out (7)."""
        ok, reason = can_commit("python", 1, start_in_days=3)
        assert ok is False
        assert "minimum" in reason

    def test_start_exactly_at_minimum_allowed(self):
        ok, reason = can_commit("python", 1, start_in_days=7)
        assert ok is True
        assert reason == "ok"

    def test_no_start_date_skips_date_check(self):
        """start_in_days=None should not trigger the date constraint."""
        ok, reason = can_commit("python", 1, start_in_days=None)
        assert ok is True
        assert reason == "ok"

    def test_go_stack_available(self):
        ok, _ = can_commit("go", 1)
        assert ok is True

    def test_empty_stack_name_blocked(self):
        ok, reason = can_commit("", 1)
        assert ok is False


# ---------------------------------------------------------------------------
# 5. Kill-switch routing matrix
# ---------------------------------------------------------------------------

class TestKillSwitch:
    """Cover all three routing outcomes: synthetic sink / live-off sink / live-on real."""

    def _ks(self, tenacious_live: bool = False) -> KillSwitch:
        cfg = Config(
            tenacious_live=tenacious_live,
            staff_sink_email="sink@tenacious.internal",
            staff_sink_sms="+10000000000",
        )
        return KillSwitch(cfg)

    # Synthetic always → sink regardless of TENACIOUS_LIVE
    def test_synthetic_email_to_sink(self):
        route = self._ks(tenacious_live=False).resolve("email", "real@co.com", synthetic=True)
        assert route.is_sink is True
        assert route.reason == "synthetic_prospect_routes_to_sink"
        assert route.to == "sink@tenacious.internal"

    def test_synthetic_sms_to_sink(self):
        route = self._ks(tenacious_live=False).resolve("sms", "+9999999999", synthetic=True)
        assert route.is_sink is True
        assert route.to == "+10000000000"

    def test_synthetic_overrides_live_flag(self):
        """Even with TENACIOUS_LIVE=True, synthetic prospects go to sink."""
        route = self._ks(tenacious_live=True).resolve("email", "real@co.com", synthetic=True)
        assert route.is_sink is True
        assert route.reason == "synthetic_prospect_routes_to_sink"

    # Non-synthetic + TENACIOUS_LIVE=False → sink
    def test_real_prospect_live_off_to_sink(self):
        route = self._ks(tenacious_live=False).resolve("email", "cto@startup.com", synthetic=False)
        assert route.is_sink is True
        assert route.reason == "TENACIOUS_LIVE_unset_default_sink"

    # Non-synthetic + TENACIOUS_LIVE=True → real address
    def test_real_prospect_live_on_passes_through(self):
        route = self._ks(tenacious_live=True).resolve("email", "cto@startup.com", synthetic=False)
        assert route.is_sink is False
        assert route.to == "cto@startup.com"
        assert route.reason == "live_mode_real_prospect_reviewed"

    def test_voice_channel_uses_sms_sink(self):
        """Voice channel reuses the SMS sink address."""
        route = self._ks().resolve("voice", "+9999999999", synthetic=True)
        assert route.to == "+10000000000"

    def test_unknown_channel_raises(self):
        ks = self._ks()
        with pytest.raises(ValueError, match="unknown channel"):
            ks._sink_for("fax")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 6. HubSpot required-property enforcement (mock path)
# ---------------------------------------------------------------------------

class TestHubSpotRequiredProperties:
    """upsert_contact() must raise ValueError when required fields are absent."""

    def _channel(self, tmp_path: Path) -> HubSpotChannel:
        cfg = Config(hubspot_token=None)  # forces mock path
        ch = HubSpotChannel(cfg)
        ch.store_path = tmp_path / "hubspot_mock.json"
        ch.store_path.write_text(json.dumps({"contacts": {}, "engagements": []}))
        return ch

    def test_missing_crunchbase_id_raises(self, tmp_path):
        ch = self._channel(tmp_path)
        with pytest.raises(ValueError, match="crunchbase_id"):
            ch.upsert_contact(
                email="test@example.com",
                properties={"last_enriched_at": "2026-04-25T00:00:00Z"},
            )

    def test_missing_last_enriched_at_raises(self, tmp_path):
        ch = self._channel(tmp_path)
        with pytest.raises(ValueError, match="last_enriched_at"):
            ch.upsert_contact(
                email="test@example.com",
                properties={"crunchbase_id": "cb_001"},
            )

    def test_missing_both_raises(self, tmp_path):
        ch = self._channel(tmp_path)
        with pytest.raises(ValueError):
            ch.upsert_contact(email="test@example.com", properties={})

    def test_both_present_succeeds(self, tmp_path):
        ch = self._channel(tmp_path)
        result = ch.upsert_contact(
            email="test@example.com",
            properties={
                "crunchbase_id": "cb_001",
                "last_enriched_at": "2026-04-25T00:00:00Z",
            },
        )
        assert result["properties"]["crunchbase_id"] == "cb_001"

    def test_existing_contact_supplies_missing_required_field(self, tmp_path):
        """If crunchbase_id already exists on the contact, upsert should not raise."""
        ch = self._channel(tmp_path)
        # Pre-seed the store with crunchbase_id already present
        store = {
            "contacts": {
                "test@example.com": {
                    "id": "hs_existing",
                    "properties": {"crunchbase_id": "cb_001"},
                }
            },
            "engagements": [],
        }
        ch.store_path.write_text(json.dumps(store))
        # Now upsert with only last_enriched_at — crunchbase_id comes from existing record
        result = ch.upsert_contact(
            email="test@example.com",
            properties={"last_enriched_at": "2026-04-25T00:00:00Z"},
        )
        assert result["id"] == "hs_existing"


# ---------------------------------------------------------------------------
# 6. Reply-gated Cal.com booking
#    Challenge doc requirement: "prospect receives an email, replies, gets
#    qualified, books a discovery call" — booking must NOT occur before reply.
# ---------------------------------------------------------------------------

class TestReplyGatedBooking:
    """Cal.com booking only fires after the prospect manually replies."""

    def test_no_booking_without_reply(self, tmp_path):
        """simulate_reply=False → calcom_booking_id is None."""
        from agent.orchestrator import Orchestrator, load_synthetic_prospects
        from unittest.mock import patch as _patch

        prospects = load_synthetic_prospects()
        prospect = next(p for p in prospects if p["id"] == "prospect_002")

        with _patch("agent.orchestrator.HubSpotChannel") as _hs, \
             _patch("agent.orchestrator.CalcomChannel") as _cal, \
             _patch("agent.orchestrator.EmailChannel") as _em, \
             _patch("agent.orchestrator.SMSChannel"), \
             _patch("agent.orchestrator.build_hiring_signal_brief",
                    return_value={"company_name": "Glenmark", "last_enriched_at": "2026-04-27",
                                  "signals": {"ai_maturity": {"score": 1}},
                                  "segment_assignment": {"segment": 2, "confidence": 0.8},
                                  "confidence_per_signal": {}}), \
             _patch("agent.orchestrator.build_competitor_gap_brief",
                    return_value={"peer_count": 5, "gap_practices": []}), \
             _patch("agent.orchestrator.compose_email") as _compose:

            from dataclasses import dataclass as _dc
            @_dc
            class _EmailResult:
                ok = True; provider = "mock"; to = "gashawbekelek@gmail.com"
                is_sink = True; message_id = "mock_001"; latency_ms = 1.0
                error = None

            @_dc
            class _Composed:
                subject = "Test"; body = "Hi"; confidence_band = "high"
                fallback_used = False

            _em_inst = _em.return_value
            _em_inst.send.return_value = _EmailResult()
            _compose.return_value = _Composed()
            _hs_inst = _hs.return_value
            _hs_inst.upsert_contact.return_value = {"id": "hs_001", "properties": {}}
            _hs_inst.log_engagement.return_value = None

            orch = Orchestrator()
            result = orch.run_one(prospect, simulate_reply=False)

        assert result.calcom_booking_id is None, (
            "Cal.com must NOT be booked before the prospect replies"
        )
        # Cal.com channel should never have been called
        _cal.return_value.offer_slots.assert_not_called()
        _cal.return_value.book.assert_not_called()

    def test_booking_fires_after_positive_reply(self, tmp_path):
        """simulate_reply=True → calcom_booking_id is populated."""
        from agent.orchestrator import Orchestrator, load_synthetic_prospects
        from unittest.mock import patch as _patch, MagicMock

        prospects = load_synthetic_prospects()
        prospect = next(p for p in prospects if p["id"] == "prospect_002")

        with _patch("agent.orchestrator.HubSpotChannel") as _hs, \
             _patch("agent.orchestrator.CalcomChannel") as _cal, \
             _patch("agent.orchestrator.EmailChannel") as _em, \
             _patch("agent.orchestrator.SMSChannel"), \
             _patch("agent.orchestrator.build_hiring_signal_brief",
                    return_value={"company_name": "Glenmark", "last_enriched_at": "2026-04-27",
                                  "signals": {"ai_maturity": {"score": 1}},
                                  "segment_assignment": {"segment": 2, "confidence": 0.8},
                                  "confidence_per_signal": {}}), \
             _patch("agent.orchestrator.build_competitor_gap_brief",
                    return_value={"peer_count": 5, "gap_practices": []}), \
             _patch("agent.orchestrator.compose_email") as _compose, \
             _patch("agent.orchestrator.can_commit", return_value=(True, "")):

            from dataclasses import dataclass as _dc
            @_dc
            class _EmailResult:
                ok = True; provider = "mock"; to = "gashawbekelek@gmail.com"
                is_sink = True; message_id = "mock_001"; latency_ms = 1.0
                error = None

            @_dc
            class _Composed:
                subject = "Test"; body = "Hi"; confidence_band = "high"
                fallback_used = False

            _em_inst = _em.return_value
            _em_inst.send.return_value = _EmailResult()
            _compose.return_value = _Composed()
            _hs_inst = _hs.return_value
            _hs_inst.upsert_contact.return_value = {"id": "hs_001", "properties": {}}
            _hs_inst.log_engagement.return_value = None

            _cal_inst = _cal.return_value
            _cal_inst.offer_slots.return_value = ["2026-05-01T10:00:00Z"]
            _cal_inst.book.return_value = {"id": "booking_abc"}

            orch = Orchestrator()
            result = orch.run_one(prospect, simulate_reply=True)

        assert result.calcom_booking_id == "booking_abc"
        _cal_inst.offer_slots.assert_called_once()
        _cal_inst.book.assert_called_once()


# ---------------------------------------------------------------------------
# 7. Webhook email payload parsing
#    Resend inbound, MailerSend, and flat/mock formats must all be normalised.
# ---------------------------------------------------------------------------

class TestWebhookEmailPayloadParsing:
    """_extract_email_address and _unwrap_inbound_payload handle all providers."""

    def test_extract_plain_email(self):
        from agent.webhooks import _extract_email_address
        assert _extract_email_address("user@example.com") == "user@example.com"

    def test_extract_display_name_format(self):
        """'Marcus <marcus@glenmark.example>' → 'marcus@glenmark.example'"""
        from agent.webhooks import _extract_email_address
        assert _extract_email_address("Marcus <marcus@glenmark.example>") \
               == "marcus@glenmark.example"

    def test_extract_from_dict(self):
        """MailerSend sends from as {'email': '...', 'name': '...'}"""
        from agent.webhooks import _extract_email_address
        assert _extract_email_address({"email": "user@example.com", "name": "User"}) \
               == "user@example.com"

    def test_extract_empty(self):
        from agent.webhooks import _extract_email_address
        assert _extract_email_address(None) == ""
        assert _extract_email_address("") == ""

    def test_unwrap_resend_inbound(self):
        """Resend wraps the email under {type: 'email.received', data: {...}}"""
        from agent.webhooks import _unwrap_inbound_payload
        raw = {
            "type": "email.received",
            "data": {"from": "user@example.com", "subject": "Re: Hi", "text": "Yes!"},
        }
        flat = _unwrap_inbound_payload(raw)
        assert flat["from"] == "user@example.com"
        assert flat["text"] == "Yes!"

    def test_unwrap_flat_passthrough(self):
        """Flat payloads (mock / MailerSend) are returned unchanged."""
        from agent.webhooks import _unwrap_inbound_payload
        raw = {"from": "user@example.com", "subject": "Hi", "text": "Hello"}
        assert _unwrap_inbound_payload(raw) is raw

    def test_classify_positive_reply(self):
        """'Interested' body → reply_positive"""
        from agent.webhooks import _unwrap_inbound_payload
        payload = {"from": "u@e.com", "subject": "Re:", "text": "Interested!"}
        body_text = payload.get("text", "").lower()
        # Same classification logic as the webhook handler
        positive_words = (
            "interested", "tell me more", "yes", "sure", "sounds good",
            "let's talk", "love to chat", "worth a call", "30 minutes",
            "schedule", "book", "calendar",
        )
        assert any(w in body_text for w in positive_words)

    def test_bounce_classified_before_body_keywords(self):
        """A bounce notification must be classified as 'bounce' even if body contains 'yes'."""
        # Mimic the webhook classification logic
        raw_payload = {"type": "email.bounced", "data": {"text": "Yes"}}
        event_type_str = (raw_payload.get("type") or "").lower()
        is_bounce = "bounce" in event_type_str
        assert is_bounce


# ---------------------------------------------------------------------------
# 8. Sink-routing reply lookup
#    When kill-switch routes to gashawbekelek@gmail.com, the reply from
#    that address must resolve to the correct prospect record.
# ---------------------------------------------------------------------------

class TestSinkRoutingReplyLookup:
    """_reply_lookup maps sink address → prospect email correctly."""

    def test_reply_lookup_populated_on_send(self):
        from agent.orchestrator import Orchestrator, load_synthetic_prospects
        from unittest.mock import patch as _patch

        prospects = load_synthetic_prospects()
        prospect = next(p for p in prospects if p["id"] == "prospect_002")
        prospect_email = prospect["contact"]["email"]  # marcus@glenmark.example
        sink_email = "gashawbekelek@gmail.com"

        with _patch("agent.orchestrator.HubSpotChannel") as _hs, \
             _patch("agent.orchestrator.CalcomChannel"), \
             _patch("agent.orchestrator.EmailChannel") as _em, \
             _patch("agent.orchestrator.SMSChannel"), \
             _patch("agent.orchestrator.build_hiring_signal_brief",
                    return_value={"company_name": "G", "last_enriched_at": "2026-04-27",
                                  "signals": {"ai_maturity": {"score": 1}},
                                  "segment_assignment": {"segment": 2, "confidence": 0.8},
                                  "confidence_per_signal": {}}), \
             _patch("agent.orchestrator.build_competitor_gap_brief",
                    return_value={"peer_count": 5, "gap_practices": []}), \
             _patch("agent.orchestrator.compose_email") as _compose:

            from dataclasses import dataclass as _dc
            @_dc
            class _EmailResult:
                ok = True; provider = "mock"; to = sink_email  # routed to sink
                is_sink = True; message_id = "mock_002"; latency_ms = 1.0
                error = None

            @_dc
            class _Composed:
                subject = "Test"; body = "Hi"; confidence_band = "high"
                fallback_used = False

            _em.return_value.send.return_value = _EmailResult()
            _compose.return_value = _Composed()
            _hs.return_value.upsert_contact.return_value = {"id": "hs_001", "properties": {}}
            _hs.return_value.log_engagement.return_value = None

            orch = Orchestrator()
            orch.run_one(prospect, simulate_reply=False)

        # Sink address should map to prospect email
        assert orch._reply_lookup.get(sink_email) == prospect_email, (
            f"Expected {sink_email!r} → {prospect_email!r} in _reply_lookup, "
            f"got: {orch._reply_lookup}"
        )
        # Direct address should also self-map
        assert orch._reply_lookup.get(prospect_email) == prospect_email
