"""Channel-handoff state machine.

Centralizes the rules for when to escalate between outbound channels:
  cold_outbound  → email sent, no reply yet
  warm_email     → prospect replied to email (qualifies for SMS escalation)
  warm_sms       → prospect replied via SMS (qualifies for Cal.com booking)
  meeting_booked → Cal.com booking confirmed
  declined       → prospect declined or unsubscribed
  bench_blocked  → prospect is warm but no bench capacity available

Transition rules (all enforced here, not scattered across orchestrator methods):
  cold_outbound  + email_reply_positive  → warm_email
  cold_outbound  + email_reply_negative  → declined
  warm_email     + sms_reply             → warm_sms
  warm_email     + bench_ok              → meeting_booked (book from email path)
  warm_sms       + bench_ok              → meeting_booked (book from SMS path)
  any            + unsubscribe/stop      → declined
  warm_email     + bench_blocked         → bench_blocked (route to human)
  warm_sms       + bench_blocked         → bench_blocked (route to human)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ChannelState(str, Enum):
    COLD_OUTBOUND = "cold_outbound"
    WARM_EMAIL = "warm_email"
    WARM_SMS = "warm_sms"
    MEETING_BOOKED = "meeting_booked"
    DECLINED = "declined"
    BENCH_BLOCKED = "bench_blocked"


# Which channels are open (caller may send) in each state
_OPEN_CHANNELS: dict[ChannelState, list[str]] = {
    ChannelState.COLD_OUTBOUND: ["email"],
    ChannelState.WARM_EMAIL: ["email", "sms"],
    ChannelState.WARM_SMS: ["email", "sms", "calcom"],
    ChannelState.MEETING_BOOKED: [],
    ChannelState.DECLINED: [],
    ChannelState.BENCH_BLOCKED: [],
}

# Valid event → next state, per current state
_TRANSITIONS: dict[ChannelState, dict[str, ChannelState]] = {
    ChannelState.COLD_OUTBOUND: {
        "email_reply_positive": ChannelState.WARM_EMAIL,
        "email_reply_negative": ChannelState.DECLINED,
        "email_reply_other": ChannelState.WARM_EMAIL,
        "unsubscribe": ChannelState.DECLINED,
        "bounce": ChannelState.DECLINED,
    },
    ChannelState.WARM_EMAIL: {
        "sms_reply": ChannelState.WARM_SMS,
        "calcom_booked": ChannelState.MEETING_BOOKED,
        "bench_blocked": ChannelState.BENCH_BLOCKED,
        "unsubscribe": ChannelState.DECLINED,
        "stop": ChannelState.DECLINED,
    },
    ChannelState.WARM_SMS: {
        "calcom_booked": ChannelState.MEETING_BOOKED,
        "bench_blocked": ChannelState.BENCH_BLOCKED,
        "unsubscribe": ChannelState.DECLINED,
        "stop": ChannelState.DECLINED,
    },
    ChannelState.MEETING_BOOKED: {},
    ChannelState.DECLINED: {},
    ChannelState.BENCH_BLOCKED: {
        "bench_cleared": ChannelState.WARM_EMAIL,  # human resolves and re-queues
    },
}


@dataclass
class ChannelRouter:
    """Tracks and enforces multi-channel handoff state for a single prospect.

    Usage:
        router = ChannelRouter()
        assert router.can_send("email")        # True — cold outbound allowed
        assert not router.can_send("sms")      # False — not warm yet
        router.advance("email_reply_positive")
        assert router.can_send("sms")          # True — email reply unlocks SMS
        router.advance("calcom_booked")
        assert router.state == ChannelState.MEETING_BOOKED
    """
    state: ChannelState = ChannelState.COLD_OUTBOUND
    history: list[dict[str, Any]] = field(default_factory=list)

    def advance(self, event: str, *, metadata: dict[str, Any] | None = None) -> ChannelState:
        """Apply an event and return the new state.

        Raises ValueError if the event is not valid in the current state.
        """
        transitions = _TRANSITIONS.get(self.state, {})
        if event not in transitions:
            raise ValueError(
                f"Event '{event}' is not valid in state '{self.state}'. "
                f"Valid events: {list(transitions)}"
            )
        prev = self.state
        self.state = transitions[event]
        self.history.append({"from": prev, "event": event, "to": self.state,
                              **(metadata or {})})
        return self.state

    def can_send(self, channel: str) -> bool:
        """Return True if the given channel is open in the current state."""
        return channel in _OPEN_CHANNELS.get(self.state, [])

    def next_channel(self) -> str | None:
        """Return the next recommended channel to use, or None if terminal."""
        open_ch = _OPEN_CHANNELS.get(self.state, [])
        return open_ch[-1] if open_ch else None
