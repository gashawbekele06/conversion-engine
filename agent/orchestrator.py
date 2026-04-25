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

from .bench import can_commit
from .channels import CalcomChannel, EmailChannel, HubSpotChannel, SMSChannel
from .compose import compose_email
from .config import load_config
from .enrichment import build_competitor_gap_brief, build_hiring_signal_brief
from .tracing import get_tracer
from .webhooks import register_email_reply_handler


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
        # Maps prospect phone_e164 → email so the SMS reply handler can update HubSpot.
        self._sms_phone_email: dict[str, str] = {}
        # Maps prospect email → context brief so the email reply handler can offer slots.
        self._email_brief: dict[str, dict] = {}
        self._register_sms_reply_handler()
        self._register_email_reply_handler()

    def _register_sms_reply_handler(self) -> None:
        """Register HubSpot CRM update as a callback for every inbound SMS reply.

        This is the missing link from Act II: SMSChannel.register_reply_handler()
        was wired but never called from the orchestrator. Every SMS event (reply,
        stop, help) now writes back to HubSpot so CRM state stays in sync with
        actual prospect engagement across channels.
        """
        def _on_sms_reply(kind: str, from_number: str, text: str) -> None:
            email = self._sms_phone_email.get(from_number)
            if not email:
                return  # unknown number — no CRM record to update

            if kind == "reply":
                self.hs.log_engagement(
                    email=email,
                    kind="SMS",
                    body=text,
                    metadata={"from_number": from_number, "direction": "inbound"},
                )
                # Advance CRM stage to warm_lead on first SMS reply
                self.hs.upsert_contact(
                    email=email,
                    properties={
                        "crunchbase_id": self._sms_phone_email.get(
                            from_number + "_crunchbase_id", ""
                        ),
                        "last_enriched_at": "",
                        "stage": "warm_lead_sms_reply",
                    },
                )
                # Cal.com booking from SMS path — same bench gate and booking flow
                # as the email reply path. SMS engagement is sufficient warm signal.
                brief = self._email_brief.get(email, {})
                stack = brief.get("recommended_stack", "python")
                ok, reason = can_commit(stack, engineers_requested=1)
                if not ok:
                    self.hs.log_engagement(
                        email=email,
                        kind="NOTE",
                        body=f"Bench capacity gate blocked slot offer (SMS path): {reason}",
                        metadata={"stack": stack, "direction": "internal"},
                    )
                else:
                    try:
                        slots = self.cal.offer_slots(
                            prospect_email=email,
                            timezone="UTC",
                            count=3,
                        )
                        if slots:
                            booking = self.cal.book(
                                prospect_email=email,
                                prospect_name=email,
                                when_iso=slots[0],
                                timezone="UTC",
                                context_brief=brief,
                            )
                            self._link_booking_to_hubspot(
                                email=email,
                                when_iso=slots[0],
                                booking_id=booking["id"],
                            )
                    except Exception:  # noqa: BLE001
                        pass  # booking errors must not crash the SMS handler
            elif kind == "stop":
                self.hs.log_engagement(
                    email=email,
                    kind="NOTE",
                    body="Prospect sent STOP — unsubscribed from SMS channel.",
                    metadata={"from_number": from_number, "direction": "inbound"},
                )
            elif kind == "help":
                self.hs.log_engagement(
                    email=email,
                    kind="NOTE",
                    body="Prospect sent HELP — auto-response sent.",
                    metadata={"from_number": from_number, "direction": "inbound"},
                )

        self.sms.register_reply_handler(_on_sms_reply)

    def _register_email_reply_handler(self) -> None:
        """Register HubSpot + Cal.com actions for every classified inbound email reply.

        Supported kinds (from webhooks.py classification):
          reply_positive  → log engagement, offer Cal.com slots, book if available
          reply_negative  → log engagement, update stage to declined
          unsubscribe     → log unsubscribe note, update stage to unsubscribed
          bounce          → log bounce note
          reply_other     → log engagement for human review
        """
        def _on_email_reply(kind: str, from_addr: str, subject: str, payload: dict) -> None:
            if kind == "unsubscribe":
                self.hs.log_engagement(
                    email=from_addr,
                    kind="NOTE",
                    body="Prospect unsubscribed via email reply.",
                    metadata={"subject": subject, "direction": "inbound"},
                )
                self.hs.upsert_contact(
                    email=from_addr,
                    properties={"stage": "unsubscribed"},
                )
                return

            if kind == "bounce":
                self.hs.log_engagement(
                    email=from_addr,
                    kind="NOTE",
                    body="Email bounced — address may be invalid.",
                    metadata={"subject": subject, "direction": "inbound"},
                )
                return

            # Log all other reply kinds (positive, negative, other)
            self.hs.log_engagement(
                email=from_addr,
                kind="EMAIL",
                body=payload.get("text") or payload.get("html") or "",
                metadata={"subject": subject, "direction": "inbound", "kind": kind},
            )

            if kind == "reply_positive":
                # Advance CRM stage
                self.hs.upsert_contact(
                    email=from_addr,
                    properties={"stage": "warm_lead_email_reply"},
                )
                # Bench gate: verify capacity before offering slots
                brief = self._email_brief.get(from_addr, {})
                stack = brief.get("recommended_stack", "python")
                ok, reason = can_commit(stack, engineers_requested=1)
                if not ok:
                    self.hs.log_engagement(
                        email=from_addr,
                        kind="NOTE",
                        body=f"Bench capacity gate blocked slot offer: {reason}",
                        metadata={"stack": stack, "direction": "internal"},
                    )
                    return  # route to human — do not offer slots
                # Offer and book first available slot
                try:
                    slots = self.cal.offer_slots(
                        prospect_email=from_addr,
                        timezone="UTC",
                        count=3,
                    )
                    if slots:
                        booking = self.cal.book(
                            prospect_email=from_addr,
                            prospect_name=from_addr,
                            when_iso=slots[0],
                            timezone="UTC",
                            context_brief=brief,
                        )
                        self._link_booking_to_hubspot(
                            email=from_addr,
                            when_iso=slots[0],
                            booking_id=booking["id"],
                        )
                except Exception:  # noqa: BLE001
                    pass  # booking errors must not crash the webhook handler

            elif kind == "reply_negative":
                self.hs.upsert_contact(
                    email=from_addr,
                    properties={"stage": "declined"},
                )

        register_email_reply_handler(_on_email_reply)

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

            # Register phone→email mapping so the SMS reply handler can update HubSpot
            # when an inbound SMS arrives for this prospect on any channel.
            phone = prospect["contact"].get("phone_e164", "")
            email = prospect["contact"]["email"]
            if phone:
                self._sms_phone_email[phone] = email
                self._sms_phone_email[phone + "_crunchbase_id"] = crunchbase_id

            # 1–2. Enrichment
            brief = build_hiring_signal_brief(crunchbase_id)
            gap = build_competitor_gap_brief(crunchbase_id)

            # Cache brief by email so the email reply handler can reference it
            # when offering Cal.com slots after a positive reply.
            self._email_brief[email] = brief

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
                    "icp_segment": segment_val,
                    "firstname": prospect["contact"]["first_name"],
                    "lastname": prospect["contact"]["last_name"],
                    "jobtitle": prospect["contact"]["title"],
                    "company": brief["company_name"],
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
                # 7. Bench gate: verify capacity before committing to a slot offer.
                # Infer required stack from brief; default to "python" if not specified.
                stack = brief.get("recommended_stack", "python")
                bench_ok, bench_reason = can_commit(stack, engineers_requested=1)
                if not bench_ok:
                    self.hs.log_engagement(
                        email=prospect["contact"]["email"],
                        kind="NOTE",
                        body=f"Bench capacity gate: slot offer skipped — {bench_reason}",
                        metadata={"stack": stack, "direction": "internal"},
                    )
                    attrs["bench_blocked"] = True
                    attrs["bench_reason"] = bench_reason
                else:
                    attrs["bench_blocked"] = False

                # Only proceed with booking if bench has capacity
                if bench_ok:
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
