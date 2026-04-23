"""End-to-end orchestrator — one synthetic prospect, one full thread.

Pipeline:
  1. Look up Crunchbase record
  2. Run enrichment (hiring signal brief + competitor gap brief)
  3. Compose first outbound (email)
  4. Send through the kill-switched email channel → staff sink
  5. Upsert contact in HubSpot mock with enrichment metadata
  6. Log engagement in HubSpot
  7. On (simulated) reply: offer Cal.com slots, book, mark HubSpot meeting

Satisfies Act II end-to-end requirement for the interim submission.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .channels import CalcomChannel, EmailChannel, HubSpotChannel, SMSChannel
from .compose import compose_email
from .config import load_config
from .enrichment import build_competitor_gap_brief, build_hiring_signal_brief
from .tracing import get_tracer


@dataclass
class ThreadResult:
    prospect_id: str
    company_name: str
    segment: int | None
    email_message_id: str
    hubspot_contact_id: str
    calcom_booking_id: str | None
    latency_ms: float
    is_sink: bool


class Orchestrator:
    def __init__(self) -> None:
        self.cfg = load_config()
        self.email = EmailChannel(self.cfg)
        self.sms = SMSChannel(self.cfg)
        self.hs = HubSpotChannel(self.cfg)
        self.cal = CalcomChannel(self.cfg)

    def run_one(
        self,
        prospect: dict[str, Any],
        *,
        simulate_reply: bool = True,
        book_slot_index: int = 0,
    ) -> ThreadResult:
        tracer = get_tracer()
        with tracer.trace("orchestrator.run_one", prospect_id=prospect["id"]) as attrs:
            start = time.time()
            crunchbase_id = prospect["crunchbase_id"]

            # 1–2. Enrichment
            brief = build_hiring_signal_brief(crunchbase_id)
            gap = build_competitor_gap_brief(crunchbase_id)

            # 3. Compose
            composed = compose_email(
                brief=brief,
                contact=prospect["contact"],
                competitor_gap=gap,
            )

            # 4. Send (synthetic=True → always routes to sink)
            email_res = self.email.send(
                to=prospect["contact"]["email"],
                subject=composed.subject,
                body=composed.body,
                synthetic=True,
                metadata={
                    "prospect_id": prospect["id"],
                    "confidence_band": composed.confidence_band,
                    "segment": brief.get("segment_assignment", {}).get("segment"),
                },
            )

            # 5. HubSpot upsert (enforces required crunchbase_id + last_enriched_at)
            #
            # ICP segment mapping:
            #   segment 1 → Series A/B, rapid engineering hiring
            #   segment 2 → cost-restructure / efficiency play
            #   segment 3 → CTO / VP-Eng transition (leadership change signal)
            #   segment 4 → capability gap (AI maturity score < 2)
            #
            # icp_segment is written explicitly alongside crunchbase_id so the
            # HubSpot contact record carries both enrichment provenance and
            # the segment classification that drove outreach.
            segment_val = brief.get("segment_assignment", {}).get("segment")
            contact_rec = self.hs.upsert_contact(
                email=prospect["contact"]["email"],
                properties={
                    "crunchbase_id": crunchbase_id,
                    "last_enriched_at": brief["last_enriched_at"],
                    "icp_segment": segment_val,          # explicit ICP segment field
                    "first_name": prospect["contact"]["first_name"],
                    "last_name": prospect["contact"]["last_name"],
                    "title": prospect["contact"]["title"],
                    "company_name": brief["company_name"],
                    "segment": segment_val,
                    "segment_confidence": brief.get("segment_assignment", {}).get("confidence"),
                    "ai_maturity_score": (brief["signals"]["ai_maturity"] or {}).get("score"),
                    "stage": "cold_outbound_sent",
                },
            )

            # 6. Engagement log
            self.hs.log_engagement(
                email=prospect["contact"]["email"],
                kind="EMAIL",
                body=composed.body,
                metadata={"subject": composed.subject,
                          "message_id": email_res.message_id,
                          "confidence_band": composed.confidence_band},
            )

            booking_id: str | None = None
            if simulate_reply:
                # 7. Simulate the prospect replying positively → book
                slots = self.cal.offer_slots(
                    prospect_email=prospect["contact"]["email"],
                    timezone="UTC",
                    count=3,
                )
                chosen = slots[book_slot_index]
                booking = self.cal.book(
                    prospect_email=prospect["contact"]["email"],
                    prospect_name=f"{prospect['contact']['first_name']} {prospect['contact']['last_name']}",
                    when_iso=chosen,
                    timezone="UTC",
                    context_brief=brief,
                )
                booking_id = booking["id"]

                # Booking-to-HubSpot linkage:
                # Every completed Cal.com booking MUST trigger a HubSpot update
                # for the same prospect so the contact record always reflects
                # the latest meeting state. This is the authoritative integration
                # point — do not skip or make best-effort.
                self._link_booking_to_hubspot(
                    email=prospect["contact"]["email"],
                    when_iso=chosen,
                    booking_id=booking_id,
                )

            latency_ms = (time.time() - start) * 1000.0
            attrs.update({
                "segment": brief.get("segment_assignment", {}).get("segment"),
                "fallback": composed.fallback_used,
                "is_sink": email_res.is_sink,
                "latency_ms": latency_ms,
            })
            return ThreadResult(
                prospect_id=prospect["id"],
                company_name=brief["company_name"],
                segment=brief.get("segment_assignment", {}).get("segment"),
                email_message_id=email_res.message_id,
                hubspot_contact_id=contact_rec["id"],
                calcom_booking_id=booking_id,
                latency_ms=latency_ms,
                is_sink=email_res.is_sink,
            )

    def _link_booking_to_hubspot(
        self, *, email: str, when_iso: str, booking_id: str
    ) -> None:
        """Propagate a completed Cal.com booking into HubSpot.

        This is the single authoritative linkage point between Cal.com and HubSpot.
        Called after every successful booking — ensures the contact record always
        reflects the latest meeting state and that no booking is ever orphaned.
        """
        self.hs.mark_meeting_booked(
            email=email,
            when_iso=when_iso,
            calcom_booking_id=booking_id,
        )
        self.hs.log_engagement(
            email=email,
            kind="MEETING",
            body=f"Discovery call booked for {when_iso}",
            metadata={"calcom_booking_id": booking_id},
        )

    def run_all(self, prospects: list[dict[str, Any]]) -> list[ThreadResult]:
        results = []
        for p in prospects:
            results.append(self.run_one(p, simulate_reply=True))
        return results


def load_synthetic_prospects() -> list[dict[str, Any]]:
    cfg = load_config()
    path = cfg.seed_dir.parent / "synthetic_prospects.json"
    all_records = json.loads(Path(path).read_text(encoding="utf-8"))["prospects"]
    # Peers are reference data for the competitor gap brief, not outbound targets.
    return [p for p in all_records if p["id"].startswith("prospect_")]
