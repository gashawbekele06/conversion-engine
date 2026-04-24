"""AI maturity scorer (0–3 integer) with per-signal justification.

The score is a PUBLIC-SIGNAL estimate, not ground truth. Every returned
object carries:
  - `score` — the 0–3 integer
  - `confidence` — 0.0–1.0
  - `justifications` — per-input sentence the agent may cite
  - `gates` — which ICP segments this score permits

This matches the per-input weights defined in the challenge spec
(High / Medium / Low). See `data/seed/icp_definition.md`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .crunchbase import _load_sample
from ..tracing import get_tracer


# Signal weights (raw points out of 10)
WEIGHTS = {
    "ai_adjacent_roles_fraction": 3,   # High
    "named_ai_leadership": 3,           # High
    "github_org_activity": 2,           # Medium
    "exec_commentary_last_12mo": 2,     # Medium
    "modern_data_stack": 1,             # Low
    "strategic_comms": 1,               # Low (often missing)
}


@dataclass
class MaturityScore:
    score: int
    confidence: float
    points: int
    justifications: list[str] = field(default_factory=list)
    inputs_present: int = 0
    high_weight_inputs_present: int = 0

    def gates_segment_4(self) -> bool:
        return self.score >= 2


def _activity_to_points(activity: str) -> int:
    return {"none": 0, "low": 1, "medium": 2, "high": 3}.get(activity, 0)


def score_ai_maturity(crunchbase_id: str) -> MaturityScore | None:
    tracer = get_tracer()
    with tracer.trace("ai_maturity.score", crunchbase_id=crunchbase_id) as attrs:
        rec = _load_sample().get(crunchbase_id)
        if not rec:
            attrs["found"] = False
            # Absence of a public record is NOT proof of low AI maturity.
            # A quiet-but-sophisticated company (no public GitHub, no press) scores
            # the same as a genuinely low-maturity company. Callers must treat
            # None as "unknown", not as score=0. See data/seed/icp_definition.md.
            return None
        inputs = rec["signals"].get("ai_maturity_inputs", {})
        points = 0
        justifications: list[str] = []
        inputs_present = 0
        high_weight_present = 0

        frac = float(inputs.get("ai_adjacent_roles_fraction") or 0)
        if frac > 0:
            inputs_present += 1
            high_weight_present += 1
            sub = WEIGHTS["ai_adjacent_roles_fraction"] if frac >= 0.15 else 1
            points += sub
            justifications.append(
                f"AI-adjacent roles are {frac:.0%} of engineering openings (weight=high)"
            )

        if inputs.get("named_ai_leadership"):
            inputs_present += 1
            high_weight_present += 1
            points += WEIGHTS["named_ai_leadership"]
            justifications.append("Named AI/ML leadership on the public team page (weight=high)")

        gh = inputs.get("github_org_activity", "none")
        gh_pts = _activity_to_points(gh)
        if gh_pts > 0:
            inputs_present += 1
            points += min(gh_pts, WEIGHTS["github_org_activity"])
            justifications.append(f"Public GitHub org activity: {gh} (weight=medium)")

        exec_ct = int(inputs.get("exec_commentary_last_12mo") or 0)
        if exec_ct > 0:
            inputs_present += 1
            points += min(exec_ct, WEIGHTS["exec_commentary_last_12mo"])
            justifications.append(
                f"{exec_ct} executive posts/talks in the last 12 months naming AI (weight=medium)"
            )

        stack = inputs.get("modern_data_stack") or []
        if stack:
            inputs_present += 1
            points += WEIGHTS["modern_data_stack"]
            justifications.append(
                f"Modern data/ML stack signal: {', '.join(stack)} (weight=low)"
            )

        if inputs.get("public_rfp_or_blog"):
            inputs_present += 1
            high_weight_present += 1  # a public build signal is high-weight in practice
            points += 2
            justifications.append(f"Public build signal: {inputs['public_rfp_or_blog']}")

        # Map raw points (0–12) onto 0–3 integer.
        if points <= 1:
            score = 0
        elif points <= 4:
            score = 1
        elif points <= 7:
            score = 2
        else:
            score = 3

        # Confidence: weight by number of inputs AND how many are high-weight.
        confidence = min(
            1.0,
            0.2 * inputs_present + 0.2 * high_weight_present,
        )

        result = MaturityScore(
            score=score,
            confidence=round(confidence, 2),
            points=points,
            justifications=justifications,
            inputs_present=inputs_present,
            high_weight_inputs_present=high_weight_present,
        )
        attrs["score"] = result.score
        attrs["confidence"] = result.confidence
        return result
