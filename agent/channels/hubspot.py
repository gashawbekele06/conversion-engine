"""HubSpot CRM — MCP-style tool surface, mock-backed by default.

The production path talks to the HubSpot Developer Sandbox MCP server
(nine tools, 100 RPS per 10s window). The mock path stores contact
state in a JSON file so the Act II end-to-end flow produces a verifiable
record.

Every conversation event MUST write back here. Every lead object MUST
reference a Crunchbase ID (contacts.properties.crunchbase_id) and an
`last_enriched_at` timestamp — the evidence-graph audit checks for these.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ..config import Config, load_config
from ..tracing import get_tracer


class HubSpotChannel:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or load_config()
        self.store_path = Path(__file__).resolve().parents[2] / "eval" / "traces" / "hubspot_mock.json"
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.store_path.exists():
            self.store_path.write_text(json.dumps({"contacts": {}, "engagements": []}, indent=2))

    def _load(self) -> dict[str, Any]:
        return json.loads(self.store_path.read_text(encoding="utf-8"))

    def _save(self, data: dict[str, Any]) -> None:
        self.store_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    # ---- MCP-style tools ----

    def upsert_contact(self, *, email: str, properties: dict[str, Any]) -> dict[str, Any]:
        tracer = get_tracer()
        with tracer.trace("hubspot.upsert_contact", email=email) as attrs:
            data = self._load()
            existing = data["contacts"].get(email, {})
            # Enforce required properties per audit.
            required = {"crunchbase_id", "last_enriched_at"}
            missing = required - set(properties.keys()) - set(existing.get("properties", {}).keys())
            if missing:
                raise ValueError(f"upsert_contact missing required properties: {sorted(missing)}")
            existing_props = existing.get("properties", {})
            existing_props.update(properties)
            data["contacts"][email] = {
                "id": existing.get("id") or f"hs_{int(time.time()*1000)}",
                "properties": existing_props,
                "updated_at": time.time(),
            }
            self._save(data)
            attrs["hubspot_id"] = data["contacts"][email]["id"]
            return data["contacts"][email]

    def log_engagement(self, *, email: str, kind: str, body: str,
                       metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        tracer = get_tracer()
        with tracer.trace("hubspot.log_engagement", email=email, kind=kind) as attrs:
            data = self._load()
            engagement = {
                "id": f"eng_{int(time.time()*1000)}",
                "email": email,
                "kind": kind,  # "EMAIL", "SMS", "NOTE", "MEETING"
                "body": body,
                "metadata": metadata or {},
                "ts": time.time(),
            }
            data["engagements"].append(engagement)
            self._save(data)
            attrs["engagement_id"] = engagement["id"]
            return engagement

    def mark_meeting_booked(self, *, email: str, when_iso: str, calcom_booking_id: str) -> None:
        tracer = get_tracer()
        with tracer.trace("hubspot.mark_meeting_booked", email=email) as attrs:
            data = self._load()
            contact = data["contacts"].setdefault(email, {"properties": {}})
            contact["properties"]["next_meeting_iso"] = when_iso
            contact["properties"]["calcom_booking_id"] = calcom_booking_id
            contact["properties"]["stage"] = "discovery_booked"
            self._save(data)
            attrs["when"] = when_iso
