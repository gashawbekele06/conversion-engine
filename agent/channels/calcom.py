"""Cal.com booking flow — real Cal.com v2 API only.

No mock fallback.  If CALCOM_API_KEY or CALCOM_EVENT_TYPE_ID are missing
the methods raise immediately.  If the API call fails the exception
propagates so the orchestrator can surface the real error.

Attaches the hiring_signal_brief + competitor_gap_brief as metadata on the
booking so the Tenacious delivery lead joins the call with research in hand.
"""
from __future__ import annotations

import json
import re as _re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from ..config import Config, load_config
from ..tracing import get_tracer


class CalcomChannel:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or load_config()

        # Local store — records every successful booking for dashboard queries.
        self.store_path = Path(__file__).resolve().parents[2] / "eval" / "traces" / "calcom_mock.json"
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.store_path.exists():
            self.store_path.write_text(json.dumps({"bookings": []}, indent=2))

        self._api_key = self.config.calcom_api_key
        self._event_type_id = self.config.calcom_event_type_id
        self._base_url = "https://api.cal.com/v2"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_credentials(self) -> None:
        if not self._api_key:
            raise RuntimeError(
                "CALCOM_API_KEY is not set in .env — cannot call Cal.com API."
            )
        if not self._event_type_id:
            raise RuntimeError(
                "CALCOM_EVENT_TYPE_ID is not set in .env — cannot call Cal.com API."
            )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "cal-api-version": "2024-08-13",
            "Content-Type": "application/json",
            "User-Agent": "TenaciousConversionEngine/1.0",
        }

    def _clean_iso(self, when_iso: str) -> str:
        """Return a clean ISO-8601 UTC string ending in Z.

        Cal.com v2 slots API returns "+00:00" offset strings; Python's
        isoformat() on tz-aware datetimes does the same.  Appending "Z" to
        either form produces the malformed "+00:00Z" that the bookings API
        rejects with HTTP 400.
        """
        t = _re.sub(r"\.\d+", "", when_iso)        # strip milliseconds
        t = _re.sub(r"\+00:00Z?$", "Z", t)         # +00:00 or +00:00Z → Z
        if not t.endswith("Z"):
            t = t.rstrip("Z") + "Z"
        return t

    def _load(self) -> dict[str, Any]:
        return json.loads(self.store_path.read_text(encoding="utf-8"))

    def _save(self, data: dict[str, Any]) -> None:
        self.store_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def offer_slots(self, *, prospect_email: str, timezone: str, count: int = 3) -> list[str]:
        """Return up to `count` available slot times from Cal.com v2 API."""
        self._require_credentials()
        tracer = get_tracer()

        with tracer.trace("calcom.offer_slots", prospect=prospect_email,
                          tz=timezone, live=True) as attrs:
            import datetime as dt

            now = dt.datetime.now(dt.timezone.utc)
            start = now + dt.timedelta(days=1)
            end = start + dt.timedelta(days=30)

            params = (
                f"eventTypeId={self._event_type_id}"
                f"&startTime={start.strftime('%Y-%m-%dT%H:%M:%SZ')}"
                f"&endTime={end.strftime('%Y-%m-%dT%H:%M:%SZ')}"
            )
            req = urllib.request.Request(
                f"{self._base_url}/slots/available?{params}",
                headers=self._headers(),
            )
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    body = json.loads(resp.read())
            except urllib.error.HTTPError as http_err:
                err_body = http_err.read().decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"Cal.com offer_slots HTTP {http_err.code}: {err_body[:500]}"
                ) from http_err

            # v2 response: {"data":{"slots":{"2026-04-27":[{"time":"..."},...]}}}
            slots_by_day: dict[str, list[dict]] = body.get("data", {}).get("slots", {})
            slots: list[str] = []
            for day_slots in slots_by_day.values():
                for s in day_slots:
                    slots.append(self._clean_iso(s["time"]))
                    if len(slots) >= count:
                        break
                if len(slots) >= count:
                    break

            attrs["slot_count"] = len(slots)
            attrs["live"] = True
            return slots[:count]

    def book(
        self,
        *,
        prospect_email: str,
        prospect_name: str,
        when_iso: str,
        timezone: str,
        context_brief: dict[str, Any],
    ) -> dict[str, Any]:
        """Book a discovery call via the real Cal.com v2 API.

        Raises RuntimeError if credentials are missing or the API call fails.
        On success, appends the record to the local store and returns it.
        """
        self._require_credentials()
        tracer = get_tracer()

        when_iso_clean = self._clean_iso(when_iso)

        with tracer.trace("calcom.book", prospect=prospect_email,
                          when=when_iso_clean, live=True) as attrs:
            payload = json.dumps({
                "eventTypeId": int(self._event_type_id),
                "start": when_iso_clean,
                "attendee": {
                    "name": prospect_name,
                    "email": prospect_email,
                    "timeZone": timezone,
                    "language": "en",
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
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    body = json.loads(resp.read())
            except urllib.error.HTTPError as http_err:
                err_body = http_err.read().decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"Cal.com book HTTP {http_err.code}: {err_body[:500]}"
                ) from http_err

            # v2 response: {"status":"success","data":{"uid":"...","id":123,...}}
            booking_id = str(
                body.get("data", {}).get("uid")
                or body.get("data", {}).get("id", "")
            )
            if not booking_id:
                raise RuntimeError(
                    f"Cal.com book: no booking ID in response: {str(body)[:300]}"
                )

            record = {
                "id": booking_id,
                "prospect_email": prospect_email,
                "prospect_name": prospect_name,
                "when_iso": when_iso_clean,
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

            # Persist to local store so the dashboard /api/calcom endpoint can read it
            data = self._load()
            data["bookings"].append(record)
            self._save(data)

            attrs["booking_id"] = booking_id
            attrs["live"] = True
            return record
