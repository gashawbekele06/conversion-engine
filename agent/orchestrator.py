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
            contact_rec = self.hs.upsert_contact(
                email=prospect["contact"]["email"],
                properties={
                    "crunchbase_id": crunchbase_id,
                    "last_enriched_at": brief["last_enriched_at"],
                    "first_name": prospect["contact"]["first_name"],
                    "last_name": prospect["contact"]["last_name"],
                    "title": prospect["contact"]["title"],
                    "company_name": brief["company_name"],
                    "segment": brief.get("segment_assignment", {}).get("segment"),
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
                self.hs.mark_meeting_booked(
                    email=prospect["contact"]["email"],
                    when_iso=chosen,
                    calcom_booking_id=booking_id,
                )
                self.hs.log_engagement(
                    email=prospect["contact"]["email"],
                    kind="MEETING",
                    body=f"Discovery call booked for {chosen}",
                    metadata={"calcom_booking_id": booking_id},
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

    def run_all(self, prospects: list[dict[str, Any]]) -> list[ThreadResult]:
        results = []
        for p in prospects:
            results.append(self.run_one(p, simulate_reply=True))
        return results


def load_synthetic_prospects() -> list[dict[str, Any]]:
    cfg = load_config()
    path = cfg.seed_dir.parent / "synthetic_prospects.json"
    return json.loads(Path(path).read_text(encoding="utf-8"))["prospects"]
