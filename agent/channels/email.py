"""Email channel — Resend primary, MailerSend fallback, mock default.

In the interim build the real HTTP client is wrapped but is ONLY
engaged when `cfg.resend_api_key` or `cfg.mailersend_api_key` is set.
Default behaviour is to append the message to a JSONL sink file so the
full Act II end-to-end flow is reproducible without live accounts.
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


@dataclass
class EmailSendResult:
    ok: bool
    provider: str
    to: str
    is_sink: bool
    message_id: str
    latency_ms: float
    error: str | None = None


class EmailChannel:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or load_config()
        self.killswitch = KillSwitch(self.config)
        self.sink_path = Path(__file__).resolve().parents[2] / "eval" / "traces" / "email_sink.jsonl"
        self.sink_path.parent.mkdir(parents=True, exist_ok=True)

    def send(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        synthetic: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> EmailSendResult:
        tracer = get_tracer()
        with tracer.trace("email.send", subject=subject, synthetic=synthetic) as attrs:
            route = self.killswitch.resolve("email", to, synthetic=synthetic)
            attrs["routed_to"] = route.to
            attrs["is_sink"] = route.is_sink
            attrs["reason"] = route.reason
            provider = self._pick_provider()
            attrs["provider"] = provider

            start = time.time()
            if provider == "mock":
                message_id = f"mock_{int(start*1000)}"
                self._write_sink(
                    {
                        "provider": "mock",
                        "to": route.to,
                        "subject": subject,
                        "body": body,
                        "metadata": metadata or {},
                        "is_sink": route.is_sink,
                        "ts": start,
                    }
                )
                return EmailSendResult(
                    ok=True, provider="mock", to=route.to, is_sink=route.is_sink,
                    message_id=message_id, latency_ms=(time.time() - start) * 1000.0,
                )

            # Real-provider code path — not exercised without API keys.
            # Imports are local so missing libs never break the mock path.
            try:
                if provider == "resend":
                    import resend  # type: ignore
                    resend.api_key = self.config.resend_api_key
                    # Use Resend's verified test sender when routing to sink/unverified domains
                    from_addr = "Tenacious <onboarding@resend.dev>"
                    resp = resend.Emails.send(
                        {"from": from_addr, "to": [route.to],
                         "subject": subject, "html": body}
                    )
                    mid = str(resp.get("id"))
                else:  # mailersend
                    import requests  # type: ignore
                    r = requests.post(
                        "https://api.mailersend.com/v1/email",
                        headers={"Authorization": f"Bearer {self.config.mailersend_api_key}"},
                        json={
                            "from": {"email": "outbound@tenacious.example"},
                            "to": [{"email": route.to}],
                            "subject": subject,
                            "html": body,
                        },
                        timeout=10,
                    )
                    r.raise_for_status()
                    mid = r.headers.get("X-Message-Id", f"ms_{int(start*1000)}")
                return EmailSendResult(
                    ok=True, provider=provider, to=route.to, is_sink=route.is_sink,
                    message_id=mid, latency_ms=(time.time() - start) * 1000.0,
                )
            except Exception as exc:  # noqa: BLE001
                # On provider failure (rate limit, auth, network) fall back to
                # mock sink so the pipeline always produces a traceable message ID.
                attrs["provider_error"] = str(exc)
                message_id = f"mock_{int(start*1000)}"
                self._write_sink(
                    {
                        "provider": f"{provider}_fallback",
                        "to": route.to,
                        "subject": subject,
                        "body": body,
                        "metadata": metadata or {},
                        "is_sink": route.is_sink,
                        "error": str(exc),
                        "ts": start,
                    }
                )
                return EmailSendResult(
                    ok=False, provider=provider, to=route.to, is_sink=route.is_sink,
                    message_id=message_id, latency_ms=(time.time() - start) * 1000.0,
                    error=str(exc),
                )

    def _pick_provider(self) -> str:
        if self.config.resend_api_key:
            return "resend"
        if self.config.mailersend_api_key:
            return "mailersend"
        return "mock"

    def _write_sink(self, row: dict[str, Any]) -> None:
        with self.sink_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
