"""SMS channel — Africa's Talking sandbox primary, mock default.

Secondary channel. Used ONLY for warm leads — prospects who have already
replied to an outbound email or explicitly requested SMS contact.

Warm-lead enforcement is structural, not just documented:
  - send() raises WarmLeadRequired if the lead has no prior engagement
  - Pass warm_lead=True only after confirming engagement in HubSpot / inbox
  - Inbound replies are dispatched to registered handlers via register_reply_handler()

STOP / HELP / UNSUB are handled in classify_inbound() and in the webhook
handler (see `agent.webhooks`).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..config import Config, load_config
from ..kill_switch import KillSwitch
from ..tracing import get_tracer


SMS_MAX_LEN = 280
STOP_WORDS = {"STOP", "UNSUB", "UNSUBSCRIBE", "QUIT", "END", "CANCEL"}
HELP_WORDS = {"HELP", "INFO"}


class WarmLeadRequired(ValueError):
    """Raised when SMS is attempted on a lead with no prior engagement."""


@dataclass
class SMSSendResult:
    ok: bool
    provider: str
    to: str
    is_sink: bool
    message_id: str
    latency_ms: float
    error: str | None = None


class SMSChannel:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or load_config()
        self.killswitch = KillSwitch(self.config)
        self.sink_path = Path(__file__).resolve().parents[2] / "eval" / "traces" / "sms_sink.jsonl"
        self.sink_path.parent.mkdir(parents=True, exist_ok=True)

        # Dispatcher: registered callbacks receive every classified inbound reply.
        # Downstream workflows plug in here without modifying this channel.
        self._reply_handlers: list[Callable[[str, str, str], None]] = []

    def register_reply_handler(self, fn: Callable[[str, str, str], None]) -> None:
        """Register a callback for inbound SMS replies.

        fn(kind: str, from_number: str, text: str) -> None
        Supported kinds: "reply" | "stop" | "help"
        """
        self._reply_handlers.append(fn)

    def dispatch_inbound(self, *, from_number: str, text: str) -> str:
        """Classify an inbound SMS and dispatch to all registered reply handlers.

        Returns the classified kind so the webhook can respond appropriately.
        """
        kind = self.classify_inbound(text)
        for handler in self._reply_handlers:
            try:
                handler(kind, from_number, text)
            except Exception:  # noqa: BLE001
                pass  # handler errors must not drop the inbound message
        return kind

    def _has_prior_engagement(self, to: str, *, from_email: str | None = None) -> bool:
        """Return True if this number has prior SMS engagement OR if from_email
        has a prior email reply — enforcing the "email reply before SMS" policy.

        A prospect who replied to outbound email is warm and qualifies for SMS.
        A prospect who only received email but never replied is cold.
        This makes the email-reply → SMS escalation path explicit in code.
        """
        # Check SMS inbound history
        if self.sink_path.exists():
            try:
                with self.sink_path.open(encoding="utf-8") as fh:
                    for line in fh:
                        row = json.loads(line)
                        if row.get("channel") == "sms_inbound" and row.get("from") == to:
                            return True
            except Exception:  # noqa: BLE001
                pass

        # Check email reply history — an email reply qualifies this lead for SMS escalation.
        # Policy: "email reply before SMS" — the prospect must have already engaged over email.
        if from_email:
            inbox_path = self.sink_path.parent / "inbox.jsonl"
            if inbox_path.exists():
                try:
                    with inbox_path.open(encoding="utf-8") as fh:
                        for line in fh:
                            row = json.loads(line)
                            if (
                                row.get("channel") == "email"
                                and row.get("from") == from_email
                                and row.get("kind") in (
                                    "reply_positive", "reply_negative", "reply_other"
                                )
                            ):
                                return True
                except Exception:  # noqa: BLE001
                    pass

        return False

    def send(
        self,
        *,
        to: str,
        body: str,
        synthetic: bool = True,
        metadata: dict[str, Any] | None = None,
        warm_lead: bool = False,
        from_email: str | None = None,
    ) -> SMSSendResult:
        """Send an SMS.

        warm_lead=True must be passed explicitly by the caller after confirming
        the lead has prior engagement. Without it, send() checks both the SMS
        inbound sink AND the email inbox for prior engagement:
          - prior SMS reply → warm
          - prior email reply → warm (email reply qualifies for SMS escalation)
          - no prior engagement of either kind → WarmLeadRequired raised

        from_email should always be provided so the email-reply path can be checked.
        Omitting it means only SMS history is consulted — the weaker check.
        """
        # Warm-lead gate: email reply before SMS is enforced in code, not just documented
        if not warm_lead and not self._has_prior_engagement(to, from_email=from_email):
            raise WarmLeadRequired(
                f"SMS blocked for {to}: no prior engagement found "
                f"(checked SMS sink and email inbox for {from_email or 'unknown'}). "
                "SMS is a warm-lead-only channel. "
                "Pass warm_lead=True only after confirming inbound reply."
            )

        tracer = get_tracer()
        with tracer.trace("sms.send", synthetic=synthetic) as attrs:
            # Truncate politely at 280; spec requires it.
            body = body[:SMS_MAX_LEN]
            route = self.killswitch.resolve("sms", to, synthetic=synthetic)
            attrs.update({"routed_to": route.to, "is_sink": route.is_sink,
                          "reason": route.reason, "body_len": len(body)})
            provider = "africastalking" if self.config.at_api_key else "mock"
            attrs["provider"] = provider

            start = time.time()
            if provider == "mock":
                mid = f"mock_sms_{int(start*1000)}"
                self._write_sink(
                    {"provider": "mock", "to": route.to, "body": body,
                     "metadata": metadata or {}, "is_sink": route.is_sink, "ts": start}
                )
                return SMSSendResult(
                    ok=True, provider="mock", to=route.to, is_sink=route.is_sink,
                    message_id=mid, latency_ms=(time.time() - start) * 1000.0,
                )

            try:
                import requests as _req  # type: ignore
                import urllib3  # type: ignore
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

                is_sandbox = self.config.at_username == "sandbox"
                # AT sandbox infrastructure is broken as of 2026-04-23:
                #   - port 443: server sends plain HTTP during TLS handshake → record layer failure
                #   - port 80: bare 400 Bad Request returned before request headers are read
                # Both behaviors confirmed via raw TCP, curl (SChannel), and Python ssl module.
                # HTTP on port 80 with allow_redirects=False is kept as the sandbox path so that
                # when AT fixes their infrastructure, a 2xx will pass through correctly.
                # Production uses HTTPS as normal.
                if is_sandbox:
                    base = "http://api.sandbox.africastalking.com"
                    extra = {"allow_redirects": False, "verify": False}
                else:
                    base = "https://api.africastalking.com"
                    extra = {}

                resp = _req.post(
                    f"{base}/version1/messaging",
                    headers={
                        "apiKey": self.config.at_api_key,
                        "Accept": "application/json",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                    data={
                        "username": self.config.at_username,
                        "to": route.to,
                        "message": body,
                    },
                    timeout=15,
                    **extra,
                )
                resp.raise_for_status()
                data = resp.json()
                mid = (
                    data.get("SMSMessageData", {})
                        .get("Recipients", [{}])[0]
                        .get("messageId", "at_ok")
                )
                return SMSSendResult(
                    ok=True, provider="africastalking", to=route.to, is_sink=route.is_sink,
                    message_id=str(mid), latency_ms=(time.time() - start) * 1000.0,
                )
            except Exception as exc:  # noqa: BLE001
                return SMSSendResult(
                    ok=False, provider="africastalking", to=route.to, is_sink=route.is_sink,
                    message_id="", latency_ms=(time.time() - start) * 1000.0, error=str(exc),
                )

    @staticmethod
    def classify_inbound(text: str) -> str:
        upper = text.strip().upper()
        first = upper.split()[0] if upper else ""
        if first in STOP_WORDS:
            return "stop"
        if first in HELP_WORDS:
            return "help"
        return "reply"

    def _write_sink(self, row: dict[str, Any]) -> None:
        with self.sink_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
