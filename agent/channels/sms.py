"""SMS channel — Africa's Talking sandbox primary, mock default.

Secondary channel. Used only for warm leads who have replied once and
asked for faster scheduling coordination. STOP / HELP / UNSUB handled
in the webhook handler (see `agent.webhooks`).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import Config, load_config
from ..kill_switch import KillSwitch
from ..tracing import get_tracer


SMS_MAX_LEN = 280
STOP_WORDS = {"STOP", "UNSUB", "UNSUBSCRIBE", "QUIT", "END", "CANCEL"}
HELP_WORDS = {"HELP", "INFO"}


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

    def send(
        self,
        *,
        to: str,
        body: str,
        synthetic: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> SMSSendResult:
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
                import africastalking  # type: ignore
                africastalking.initialize(self.config.at_username, self.config.at_api_key)
                sms = africastalking.SMS
                resp = sms.send(body, [route.to])
                mid = str(resp.get("SMSMessageData", {}).get("Message", "at_ok"))
                return SMSSendResult(
                    ok=True, provider="africastalking", to=route.to, is_sink=route.is_sink,
                    message_id=mid, latency_ms=(time.time() - start) * 1000.0,
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
