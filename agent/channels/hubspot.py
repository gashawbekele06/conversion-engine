"""HubSpot CRM — MCP-style tool surface.

Production path: uses hubspot-api-client when HUBSPOT_TOKEN is set.
Mock path: stores contact state in a JSON file (default when token absent).

Every conversation event MUST write back here. Every lead object MUST
reference a Crunchbase ID (contacts.properties.crunchbase_id) and a
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

        # Real API client — only initialised when token is present
        self._client: Any = None
        if self.config.hubspot_token:
            try:
                from hubspot import HubSpot  # type: ignore
                self._client = HubSpot(access_token=self.config.hubspot_token)
            except Exception:  # noqa: BLE001
                self._client = None  # fall back to mock silently

    # ------------------------------------------------------------------ helpers

    def _load(self) -> dict[str, Any]:
        return json.loads(self.store_path.read_text(encoding="utf-8"))

    def _save(self, data: dict[str, Any]) -> None:
        self.store_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    # ------------------------------------------------------------------ tools

    def upsert_contact(self, *, email: str, properties: dict[str, Any]) -> dict[str, Any]:
        tracer = get_tracer()
        with tracer.trace("hubspot.upsert_contact", email=email,
                          live=bool(self._client)) as attrs:
            # Enforce required properties per audit.
            required = {"crunchbase_id", "last_enriched_at"}
            existing_props: dict[str, Any] = {}

            if self._client:
                try:
                    from hubspot.crm.contacts import SimplePublicObjectInputForCreate  # type: ignore
                    from hubspot.crm.contacts.exceptions import ApiException  # type: ignore

                    # HubSpot rejects IANA-reserved .example TLD; remap to .dev for live API
                    live_email = email[:-8] + ".dev" if email.endswith(".example") else email

                    # Map orchestrator field names → HubSpot internal names.
                    # Only send properties that exist in HubSpot (standard + our custom ones).
                    _prop_map = {
                        "first_name": "firstname",
                        "last_name": "lastname",
                        "title": "jobtitle",
                        "company_name": "company",
                    }
                    _allowed = {"firstname", "lastname", "jobtitle", "company",
                                "crunchbase_id", "last_enriched_at"}
                    live_props: dict[str, Any] = {}
                    for k, v in properties.items():
                        mapped = _prop_map.get(k, k)
                        if mapped in _allowed and v is not None:
                            live_props[mapped] = str(v)

                    # Check if contact exists by email
                    search_response = self._client.crm.contacts.search_api.do_search({
                        "filterGroups": [{
                            "filters": [{
                                "propertyName": "email",
                                "operator": "EQ",
                                "value": live_email,
                            }]
                        }],
                        "properties": list(_allowed),
                        "limit": 1,
                    })
                    results = search_response.results or []
                    if results:
                        contact_id = results[0].id
                        existing_props = results[0].properties or {}
                        # Update existing contact
                        self._client.crm.contacts.basic_api.update(
                            contact_id=contact_id,
                            simple_public_object_input={"properties": live_props},
                        )
                    else:
                        # Create new contact
                        all_props = {"email": live_email, **live_props}
                        resp = self._client.crm.contacts.basic_api.create(
                            simple_public_object_input_for_create=SimplePublicObjectInputForCreate(
                                properties=all_props,
                            )
                        )
                        contact_id = resp.id

                    record = {
                        "id": contact_id,
                        "properties": {**existing_props, **properties},
                        "updated_at": time.time(),
                        "live": True,
                    }
                    attrs["hubspot_id"] = contact_id
                    attrs["live"] = True
                    # Mirror to mock store for audit trail
                    data = self._load()
                    data["contacts"][email] = record
                    self._save(data)
                    return record
                except Exception as exc:  # noqa: BLE001
                    attrs["live_error"] = str(exc)
                    # Fall through to mock

            # Mock path
            data = self._load()
            existing = data["contacts"].get(email, {})
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
        with tracer.trace("hubspot.log_engagement", email=email,
                          kind=kind, live=bool(self._client)) as attrs:
            engagement: dict[str, Any] = {
                "id": f"eng_{int(time.time()*1000)}",
                "email": email,
                "kind": kind,  # "EMAIL", "SMS", "NOTE", "MEETING"
                "body": body,
                "metadata": metadata or {},
                "ts": time.time(),
            }

            if self._client:
                try:
                    # Log as a HubSpot note engagement
                    self._client.crm.objects.notes.basic_api.create(
                        simple_public_object_input_for_create={
                            "properties": {
                                "hs_note_body": f"[{kind}] {body}",
                                "hs_timestamp": str(int(time.time() * 1000)),
                            }
                        }
                    )
                    engagement["live"] = True
                    attrs["live"] = True
                except Exception as exc:  # noqa: BLE001
                    attrs["live_error"] = str(exc)

            # Always write to local mock for audit trail
            data = self._load()
            data["engagements"].append(engagement)
            self._save(data)
            attrs["engagement_id"] = engagement["id"]
            return engagement

    def mark_meeting_booked(self, *, email: str, when_iso: str,
                            calcom_booking_id: str) -> None:
        tracer = get_tracer()
        with tracer.trace("hubspot.mark_meeting_booked", email=email,
                          live=bool(self._client)) as attrs:
            if self._client:
                try:
                    search_response = self._client.crm.contacts.search_api.do_search({
                        "filterGroups": [{
                            "filters": [{
                                "propertyName": "email",
                                "operator": "EQ",
                                "value": email,
                            }]
                        }],
                        "limit": 1,
                    })
                    results = search_response.results or []
                    if results:
                        self._client.crm.contacts.basic_api.update(
                            contact_id=results[0].id,
                            simple_public_object_input={
                                "properties": {
                                    "hs_lead_status": "IN_PROGRESS",
                                    "calcom_booking_id": calcom_booking_id,
                                }
                            },
                        )
                    attrs["live"] = True
                except Exception as exc:  # noqa: BLE001
                    attrs["live_error"] = str(exc)

            # Always update mock store
            data = self._load()
            contact = data["contacts"].setdefault(email, {"properties": {}})
            contact["properties"]["next_meeting_iso"] = when_iso
            contact["properties"]["calcom_booking_id"] = calcom_booking_id
            contact["properties"]["stage"] = "discovery_booked"
            self._save(data)
            attrs["when"] = when_iso
