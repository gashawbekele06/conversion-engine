"""Kill switch — every outbound channel routes through this gate.

Default: routes ALL outbound to the staff sink. The only way a message
reaches a real prospect address is if TENACIOUS_LIVE=1 AND the prospect
is explicitly marked `synthetic=False` (live prospects are added only
after program-staff review).

This satisfies Data-Handling Policy rule 4.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .config import Config, load_config


Channel = Literal["email", "sms", "voice"]


@dataclass
class OutboundRoute:
    """Resolved destination for an outbound message."""
    channel: Channel
    to: str
    is_sink: bool
    reason: str


class KillSwitch:
    """Single choke-point for all outbound traffic."""

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or load_config()

    def resolve(
        self,
        channel: Channel,
        intended_to: str,
        synthetic: bool = True,
    ) -> OutboundRoute:
        # Any synthetic prospect always goes to the sink, even under LIVE.
        if synthetic:
            return OutboundRoute(
                channel=channel,
                to=self._sink_for(channel),
                is_sink=True,
                reason="synthetic_prospect_routes_to_sink",
            )
        # Real prospect + LIVE flag set + explicit review required.
        if not self.config.tenacious_live:
            return OutboundRoute(
                channel=channel,
                to=self._sink_for(channel),
                is_sink=True,
                reason="TENACIOUS_LIVE_unset_default_sink",
            )
        return OutboundRoute(
            channel=channel,
            to=intended_to,
            is_sink=False,
            reason="live_mode_real_prospect_reviewed",
        )

    def _sink_for(self, channel: Channel) -> str:
        if channel == "email":
            return self.config.staff_sink_email
        if channel == "sms":
            return self.config.staff_sink_sms
        if channel == "voice":
            return self.config.staff_sink_sms  # voice rig uses SMS-style sink for now
        raise ValueError(f"unknown channel {channel!r}")
