"""HubSpot CRM — MCP-style tool surface.

Production path: uses hubspot-api-client when HUBSPOT_TOKEN is set.
HUBSPOT_TOKEN is required — raises RuntimeError if missing or SDK import fails.

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

        # Real API client — HUBSPOT_TOKEN is required.
        if not self.config.hubspot_token:
            raise RuntimeError(
                "HUBSPOT_TOKEN is not set in .env — cannot call HubSpot API."
            )
        try:
            from hubspot import HubSpot  # type: ignore
            self._client: Any = HubSpot(access_token=self.config.hubspot_token)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to initialise HubSpot SDK: {exc}"
            ) from exc

    # ------------------------------------------------------------------ helpers

    def _load(self) -> dict[str, Any]:
        return json.loads(self.store_path.read_text(encoding="utf-8"))

    def _save(self, data: dict[str, Any]) -> None:
        self.store_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    # ------------------------------------------------------------------ tools

    def upsert_contact(self, *, email: str, properties: dict[str, Any]) -> dict[str, Any]:
        tracer = get_tracer()
        with tracer.trace("hubspot.upsert_contact", email=email, live=True) as attrs:
            # Enforce required properties per audit — check BEFORE hitting live API.
            required = {"crunchbase_id", "last_enriched_at"}
            data = self._load()
            existing = data["contacts"].get(email, {})
            missing = required - set(properties.keys()) - set(existing.get("properties", {}).keys())
            if missing:
                raise ValueError(f"upsert_contact missing required properties: {sorted(missing)}")

            from hubspot.crm.contacts import SimplePublicObjectInputForCreate  # type: ignore

            # HubSpot rejects IANA-reserved .example TLD; remap to .dev for live API
            live_email = email[:-8] + ".dev" if email.endswith(".example") else email

            _prop_map = {
                "first_name": "firstname",
                "last_name": "lastname",
                "title": "jobtitle",
                "company_name": "company",
            }
            # Only send standard HubSpot properties to the live API.
            # Custom properties (crunchbase_id, last_enriched_at, icp_segment)
            # require manual creation in the HubSpot portal before they can be
            # written via API. They are stored in the local store for dashboard
            # display but excluded from the live API call to prevent 400 errors.
            _standard_hs = {"firstname", "lastname", "jobtitle", "company",
                            "phone", "website", "city", "country",
                            "hs_lead_status"}
            _stage_to_lead_status = {
                "cold_outbound_sent": "ATTEMPTED_TO_CONTACT",
                "warm_lead_email_reply": "CONNECTED",
                "warm_lead_sms_reply": "CONNECTED",
                "discovery_booked": "IN_PROGRESS",
                "declined": "UNQUALIFIED",
                "unsubscribed": "UNQUALIFIED",
            }
            live_props: dict[str, Any] = {}
            for k, v in properties.items():
                mapped = _prop_map.get(k, k)
                if mapped in _standard_hs and v is not None:
                    live_props[mapped] = str(v)
            # Auto-derive hs_lead_status from stage for the live API
            stage_val = properties.get("stage")
            if stage_val and stage_val in _stage_to_lead_status:
                live_props["hs_lead_status"] = _stage_to_lead_status[stage_val]

            existing_props: dict[str, Any] = {}
            # Check if contact exists by email
            search_response = self._client.crm.contacts.search_api.do_search({
                "filterGroups": [{
                    "filters": [{
                        "propertyName": "email",
                        "operator": "EQ",
                        "value": live_email,
                    }]
                }],
                "properties": list(_standard_hs),
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
            # Mirror to local store for dashboard audit trail
            data = self._load()
            data["contacts"][email] = record
            self._save(data)
            return record

    def log_engagement(self, *, email: str, kind: str, body: str,
                       metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        tracer = get_tracer()
        with tracer.trace("hubspot.log_engagement", email=email,
                          kind=kind, live=True) as attrs:
            engagement: dict[str, Any] = {
                "id": f"eng_{int(time.time()*1000)}",
                "email": email,
                "kind": kind,  # "EMAIL", "SMS", "NOTE", "MEETING"
                "body": body,
                "metadata": metadata or {},
                "ts": time.time(),
            }

            # Log as a HubSpot note engagement
            try:
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
                # Note: engagement notes are best-effort — don't block the pipeline
                attrs["live_error"] = str(exc)

            # Always write to local store for audit trail
            data = self._load()
            data["engagements"].append(engagement)
            self._save(data)
            attrs["engagement_id"] = engagement["id"]
            return engagement

    def mark_meeting_booked(self, *, email: str, when_iso: str,
                            calcom_booking_id: str) -> None:
        tracer = get_tracer()
        with tracer.trace("hubspot.mark_meeting_booked", email=email,
                          live=True) as attrs:
            live_email = email[:-8] + ".dev" if email.endswith(".example") else email
            search_response = self._client.crm.contacts.search_api.do_search({
                "filterGroups": [{
                    "filters": [{
                        "propertyName": "email",
                        "operator": "EQ",
                        "value": live_email,
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
                        }
                    },
                )
            attrs["live"] = True

            # Always update local store for dashboard audit trail
            data = self._load()
            contact = data["contacts"].setdefault(email, {"properties": {}})
            contact["properties"]["next_meeting_iso"] = when_iso
            contact["properties"]["calcom_booking_id"] = calcom_booking_id
            contact["properties"]["stage"] = "discovery_booked"
            self._save(data)
            attrs["when"] = when_iso
