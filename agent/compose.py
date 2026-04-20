"""Outbound composition with signal-confidence-aware phrasing.

Consumes a hiring_signal_brief + competitor_gap_brief + seed style guide,
emits an outbound email (and optionally an SMS follow-up). Phrasing
shifts automatically with confidence — this is the seed for the Act IV
mechanism.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import load_config
from .llm import LLM
from .tracing import get_tracer


@dataclass
class ComposedMessage:
    subject: str
    body: str
    channel: str  # "email" | "sms"
    confidence_band: str  # "high" | "medium" | "low"
    model: str
    fallback_used: bool


def _confidence_band(brief: dict[str, Any]) -> str:
    per = brief.get("confidence_per_signal", {})
    highest = max(per.values()) if per else 0.0
    if highest >= 0.8:
        return "high"
    if highest >= 0.5:
        return "medium"
    return "low"


def _system_prompt() -> str:
    cfg = load_config()
    style_path = cfg.seed_dir / "style_guide.md"
    style = style_path.read_text(encoding="utf-8") if style_path.exists() else ""
    return (
        "You are Tenacious Consulting's outbound SDR agent. "
        "Compose a SHORT cold email (<120 words) grounded in the hiring_signal_brief "
        "JSON passed by the user. Obey the following style guide exactly:\n\n"
        + style
        + "\n\nReturn output in the form:\nSUBJECT: <subject>\n\n<body>\n"
        "Do NOT claim any signal whose confidence_per_signal entry is below 0.55 — "
        "soften to an ask rather than an assertion."
    )


def compose_email(
    *,
    brief: dict[str, Any],
    contact: dict[str, Any],
    competitor_gap: dict[str, Any] | None = None,
) -> ComposedMessage:
    tracer = get_tracer()
    with tracer.trace("compose.email", company=brief.get("company_name")) as attrs:
        llm = LLM()
        payload = {
            "brief": brief,
            "contact": contact,
            "competitor_gap": competitor_gap,
        }
        response = llm.generate(
            system=_system_prompt(),
            user=json.dumps(payload, default=str),
            temperature=0.3,
            max_tokens=380,
        )
        subject, body = _split_subject_body(response.text)
        band = _confidence_band(brief)
        attrs.update({"confidence_band": band, "fallback": response.fallback_used,
                      "model": response.model})
        return ComposedMessage(
            subject=subject,
            body=body,
            channel="email",
            confidence_band=band,
            model=response.model,
            fallback_used=response.fallback_used,
        )


def _split_subject_body(text: str) -> tuple[str, str]:
    if "SUBJECT:" in text:
        head, _, rest = text.partition("SUBJECT:")
        subject_line, _, body = rest.partition("\n")
        return subject_line.strip(), body.strip()
    first, _, rest = text.partition("\n")
    return first.strip(), rest.strip() or first.strip()
