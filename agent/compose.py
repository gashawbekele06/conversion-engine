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


# ---------------------------------------------------------------------------
# Peer-count gate constants (hyperparameters for P-028 fix — method.md §3)
# ---------------------------------------------------------------------------
PEER_COUNT_SUPPRESS = 3   # below this: no gap claim
PEER_COUNT_HEDGE = 5      # below this: hedged language; at/above: full assertion


def _compose_gap_section(competitor_gap: dict[str, Any]) -> str:
    """Return gap paragraph for the email body, gated by peer_count.

    Implements the P-028 fix: when fewer than PEER_COUNT_SUPPRESS viable sector
    peers exist the statistical basis for a trend claim is absent and the section
    is suppressed entirely. Between PEER_COUNT_SUPPRESS and PEER_COUNT_HEDGE a
    hedged form is used. At or above PEER_COUNT_HEDGE the full assertion is used.
    """
    peer_count = competitor_gap.get("peer_count", 0)
    gap_practices = competitor_gap.get("gap_practices", [])

    if peer_count < PEER_COUNT_SUPPRESS or not gap_practices:
        # Structural gate — suppresses gap language when sample is too small.
        # Callers receive an empty string; compose_email omits the gap section.
        return ""

    practice_text = gap_practices[0].get("practice", "") if gap_practices else ""
    if not practice_text:
        return ""

    if peer_count < PEER_COUNT_HEDGE:
        return (
            f"A small number of companies in your sector are already doing "
            f"{practice_text} — worth a conversation about whether the timing "
            f"is right for you."
        )
    return (
        f"{peer_count} companies in your sector show evidence of {practice_text}. "
        f"Based on public signals, your team is not yet there. "
        f"That gap is exactly where Tenacious has placed dedicated squads."
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

        # Apply peer-count gate before passing competitor_gap to the LLM.
        # This prevents the model from ever seeing—and then asserting—a gap
        # claim that lacks statistical grounding (P-028).
        gap_section = _compose_gap_section(competitor_gap or {}) if competitor_gap else ""
        peer_count = (competitor_gap or {}).get("peer_count", 0)
        attrs["peer_count"] = peer_count
        attrs["gap_suppressed"] = not bool(gap_section)

        # Pass the pre-computed gap section so the LLM uses it verbatim
        # rather than regenerating it from the raw brief (which has no gate).
        payload = {
            "brief": brief,
            "contact": contact,
            "competitor_gap": competitor_gap,
            "gap_section_override": gap_section,  # empty string = suppressed
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
