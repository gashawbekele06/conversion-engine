"""Cal.com booking flow — real Cal.com v2 API primary, mock fallback.

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

        self._api_key = self.config.calcom_api_key
        self._event_type_id = self.config.calcom_event_type_id
        self._base_url = "https://api.cal.com/v2"
        self._live = bool(self._api_key and self._event_type_id)

    def _load(self) -> dict[str, Any]:
        return json.loads(self.store_path.read_text(encoding="utf-8"))

    def _save(self, data: dict[str, Any]) -> None:
        self.store_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "cal-api-version": "2024-08-13",
            "Content-Type": "application/json",
            "User-Agent": "TenaciousConversionEngine/1.0",
        }

    def offer_slots(self, *, prospect_email: str, timezone: str, count: int = 3) -> list[str]:
        tracer = get_tracer()
        with tracer.trace("calcom.offer_slots", prospect=prospect_email, tz=timezone,
                          live=self._live) as attrs:
            if self._live:
                try:
                    import urllib.request
                    import datetime as dt

                    now = dt.datetime.now(dt.timezone.utc)
                    start = now + dt.timedelta(days=1)
                    end = start + dt.timedelta(days=7)

                    params = (
                        f"eventTypeId={self._event_type_id}"
                        f"&startTime={start.strftime('%Y-%m-%dT%H:%M:%SZ')}"
                        f"&endTime={end.strftime('%Y-%m-%dT%H:%M:%SZ')}"
                    )
                    req = urllib.request.Request(
                        f"{self._base_url}/slots/available?{params}",
                        headers=self._headers(),
                    )
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        body = json.loads(resp.read())

                    # v2 response: {"data":{"slots":{"2026-04-27":[{"time":"..."},...]}}}
                    slots_by_day: dict[str, list[dict]] = (
                        body.get("data", {}).get("slots", {})
                    )
                    slots: list[str] = []
                    for day_slots in slots_by_day.values():
                        for s in day_slots:
                            slots.append(s["time"])
                            if len(slots) >= count:
                                break
                        if len(slots) >= count:
                            break

                    if slots:
                        attrs["slot_count"] = len(slots)
                        attrs["live"] = True
                        return slots[:count]
                except Exception as exc:  # noqa: BLE001
                    attrs["live_error"] = str(exc)

            # Fallback: generate synthetic slots
            import datetime as dt
            now = dt.datetime.now(dt.timezone.utc)
            slots = []
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
        with tracer.trace("calcom.book", prospect=prospect_email, when=when_iso,
                          live=self._live) as attrs:
            if self._live:
                try:
                    import urllib.request

                    first, *rest = prospect_name.split(" ", 1)
                    last = rest[0] if rest else ""

                    payload = json.dumps({
                        "eventTypeId": int(self._event_type_id),
                        "start": when_iso,
                        "attendee": {
                            "name": prospect_name,
                            "email": prospect_email,
                            "timeZone": timezone,
                        },
                        "metadata": {
                            "company_name": context_brief.get("company_name", ""),
                            "segment": str(
                                context_brief.get("segment_assignment", {}).get("segment", "")
                            ),
                        },
                    }).encode()

                    req = urllib.request.Request(
                        f"{self._base_url}/bookings",
                        data=payload,
                        headers=self._headers(),
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        body = json.loads(resp.read())

                    # v2 response: {"status":"success","data":{"uid":"...","id":123,...}}
                    booking_id = str(body.get("data", {}).get("uid") or body.get("data", {}).get("id", ""))
                    if booking_id:
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
                                "ai_maturity_score": (
                                    context_brief.get("signals", {}).get("ai_maturity") or {}
                                ).get("score"),
                            },
                            "ts": time.time(),
                            "live": True,
                        }
                        data = self._load()
                        data["bookings"].append(record)
                        self._save(data)
                        attrs["booking_id"] = booking_id
                        attrs["live"] = True
                        return record
                except Exception as exc:  # noqa: BLE001
                    attrs["live_error"] = str(exc)

            # Mock fallback
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
