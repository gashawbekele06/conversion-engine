"""Cal.com booking flow — self-hosted Docker Compose primary, mock default.

Attaches the hiring_signal_brief + competitor_gap_brief as a context
document on the booking so the Tenacious delivery lead joins the call
with research already in hand.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from ..config import Config, load_config
from ..tracing import get_tracer


class CalcomChannel:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or load_config()
        self.store_path = Path(__file__).resolve().parents[2] / "eval" / "traces" / "calcom_mock.json"
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.store_path.exists():
            self.store_path.write_text(json.dumps({"bookings": []}, indent=2))

    def _load(self) -> dict[str, Any]:
        return json.loads(self.store_path.read_text(encoding="utf-8"))

    def _save(self, data: dict[str, Any]) -> None:
        self.store_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    def offer_slots(self, *, prospect_email: str, timezone: str, count: int = 3) -> list[str]:
        tracer = get_tracer()
        with tracer.trace("calcom.offer_slots", prospect=prospect_email, tz=timezone) as attrs:
            # Interim: generate synthetic slots at 10/14/16h local over next 3 business days.
            import datetime as dt
            now = dt.datetime.utcnow()
            slots: list[str] = []
            day_offset = 1
            while len(slots) < count:
                candidate = now + dt.timedelta(days=day_offset)
                if candidate.weekday() < 5:
                    for hour in (10, 14, 16):
                        if len(slots) >= count:
                            break
                        slot = candidate.replace(hour=hour, minute=0, second=0, microsecond=0)
                        slots.append(slot.isoformat() + "Z")
                day_offset += 1
            attrs["slot_count"] = len(slots)
            return slots

    def book(
        self,
        *,
        prospect_email: str,
        prospect_name: str,
        when_iso: str,
        timezone: str,
        context_brief: dict[str, Any],
    ) -> dict[str, Any]:
        tracer = get_tracer()
        with tracer.trace("calcom.book", prospect=prospect_email, when=when_iso) as attrs:
            booking_id = f"cal_{uuid.uuid4().hex[:8]}"
            data = self._load()
            record = {
                "id": booking_id,
                "prospect_email": prospect_email,
                "prospect_name": prospect_name,
                "when_iso": when_iso,
                "timezone": timezone,
                "attendee_tenacious": "delivery-lead@tenacious.internal",
                "context_brief_summary": {
                    "company_name": context_brief.get("company_name"),
                    "segment": context_brief.get("segment_assignment", {}).get("segment"),
                    "ai_maturity_score": (context_brief.get("signals", {})
                                         .get("ai_maturity") or {}).get("score"),
                },
                "ts": time.time(),
            }
            data["bookings"].append(record)
            self._save(data)
            attrs["booking_id"] = booking_id
            return record
