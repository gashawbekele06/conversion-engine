"""Competitor-gap brief builder.

Given a prospect's sector + AI maturity, identify 5–10 top-quartile
sector peers, apply the same AI-maturity scoring, compute the
prospect's rank within the sector distribution, and extract 2–3
practices the top quartile shows that the prospect does not.

Interim: cluster against the in-repo synthetic fixture. Production:
cluster against the full Crunchbase ODM sample.

Schema
------
The return value of build_competitor_gap_brief() conforms to CompetitorGapBrief.
All consumers (compose.py, channel handlers, evaluators) should reference this
dataclass for field names and types rather than hard-coding string keys.

Scoring reuse
-------------
score_ai_maturity() from .ai_maturity is called ONCE for the prospect (target)
and ONCE PER PEER. The same function, same weights, same public-signal sources.
This ensures the distribution comparison is apples-to-apples: no separate
scoring logic for competitors.

Distribution position
---------------------
target_percentile is the fraction of scored peers below the prospect's score
(0.0 = lowest, 1.0 = highest). A value of 0.25 means the prospect scores
higher than 25% of peers — in the bottom quartile.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean, quantiles
from typing import Any

from .ai_maturity import score_ai_maturity
from .crunchbase import _load_sample
from ..tracing import get_tracer


PRACTICE_CATALOG = [
    "named AI/ML leadership on public team page",
    "AI-adjacent roles as >15% of engineering openings",
    "recent public exec commentary naming AI as strategic",
    "modern data/ML stack (dbt, Databricks, Ray, vLLM, W&B)",
    "public engineering blog on model serving or evaluation",
]


@dataclass
class GapPractice:
    """A single AI practice observed in top-quartile peers but absent in the prospect.

    Fields
    ------
    practice       : Human-readable practice name (from PRACTICE_CATALOG or justification text)
    peer_count      : Number of top-quartile peers that exhibit this practice
    evidence_source : Public signal used to detect this practice (job posting / website /
                      press / GitHub / N/A if inferred from justification text)
    """
    practice: str
    peer_count: int
    evidence_source: str = "public_signal"


@dataclass
class CompetitorGapBrief:
    """Fully-typed schema for the competitor gap brief.

    All fields are derived from public signals using the same score_ai_maturity()
    function applied identically to the target prospect and every sector peer.

    Fields
    ------
    crunchbase_id           : Target prospect identifier
    sector                  : Sector key (matches data/seed/sector_taxonomy.md)
    target_score            : AI maturity score (0–3) for the prospect
    target_confidence       : Confidence of target's maturity score (0.0–1.0)
    peer_count              : Number of peers scored in the same sector
    sector_mean_score       : Mean AI maturity score across all scored peers
    top_quartile_threshold  : Minimum score to be in the top 25% of peers
    target_percentile       : Fraction of peers that score BELOW the prospect (0.0–1.0).
                              0.0 = prospect is lowest; 1.0 = prospect is highest.
                              Bottom quartile ≈ < 0.25; top quartile ≈ > 0.75.
    gap_practices           : Up to 3 practices present in top-quartile peers but not
                              in the prospect; ordered by peer_count descending
    top_quartile_peers      : Peer records with score >= top_quartile_threshold
    caveats                 : Known limitations of public-signal scoring
    error                   : Non-empty only if target record was not found
    """
    crunchbase_id: str
    sector: str
    target_score: int | None
    target_confidence: float | None
    peer_count: int
    sector_mean_score: float | None
    top_quartile_threshold: int
    target_percentile: float
    gap_practices: list[GapPractice]
    top_quartile_peers: list[dict[str, Any]]
    caveats: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "crunchbase_id": self.crunchbase_id,
            "sector": self.sector,
            "target": {
                "score": self.target_score,
                "confidence": self.target_confidence,
            },
            "peer_count": self.peer_count,
            "sector_mean_score": self.sector_mean_score,
            "top_quartile_threshold": self.top_quartile_threshold,
            "target_percentile": self.target_percentile,
            "gap_practices": [
                {
                    "practice": gp.practice,
                    "peer_count": gp.peer_count,
                    "evidence_source": gp.evidence_source,
                }
                for gp in self.gap_practices
            ],
            "top_quartile_peers": self.top_quartile_peers,
            "caveats": self.caveats,
            **({"error": self.error} if self.error else {}),
        }


def build_competitor_gap_brief(crunchbase_id: str) -> dict[str, Any]:
    """Build a competitor gap brief and return it as a plain dict.

    Internally constructs a CompetitorGapBrief dataclass (typed, documented schema)
    and calls .to_dict() for backwards-compatible dict output. Callers that want
    the typed object can call build_competitor_gap_brief_typed() instead.
    """
    return build_competitor_gap_brief_typed(crunchbase_id).to_dict()


def build_competitor_gap_brief_typed(crunchbase_id: str) -> CompetitorGapBrief:
    """Build and return a fully-typed CompetitorGapBrief.

    Scoring reuse: score_ai_maturity() is called once for the target and once per
    peer — the same function, same weights, same public-signal sources. No separate
    scoring logic exists for competitors.

    Distribution position: target_percentile is the fraction of peers whose score
    is strictly below the prospect's score. Bottom quartile ≈ < 0.25.
    """
    tracer = get_tracer()
    with tracer.trace("competitor_gap.build", crunchbase_id=crunchbase_id) as attrs:
        target_rec = _load_sample().get(crunchbase_id)
        if not target_rec:
            return CompetitorGapBrief(
                crunchbase_id=crunchbase_id,
                sector="",
                target_score=None,
                target_confidence=None,
                peer_count=0,
                sector_mean_score=None,
                top_quartile_threshold=3,
                target_percentile=0.0,
                gap_practices=[],
                top_quartile_peers=[],
                error="target not found",
            )

        sector = target_rec["sector"]
        peers = [
            r for r in _load_sample().values()
            if r["sector"] == sector and r["crunchbase_id"] != crunchbase_id
        ]

        # Score target — same score_ai_maturity() used for all peers below
        target_maturity = score_ai_maturity(crunchbase_id)

        # Score every peer with the same function (explicit reuse — not a separate scorer)
        peer_scores: list[dict[str, Any]] = []
        for peer in peers:
            s = score_ai_maturity(peer["crunchbase_id"])
            if s is None:
                continue
            peer_scores.append(
                {
                    "crunchbase_id": peer["crunchbase_id"],
                    "company_name": peer["company_name"],
                    "score": s.score,
                    "justifications": s.justifications,
                }
            )

        # Distribution + top quartile
        scores_only = [p["score"] for p in peer_scores]
        top_q = _top_quartile_threshold(scores_only)
        top_quartile = [p for p in peer_scores if p["score"] >= top_q]

        # Practice gap: practices in top-quartile peers but NOT in target
        target_justifications = set(target_maturity.justifications) if target_maturity else set()
        top_q_justifications: dict[str, int] = {}
        for peer in top_quartile:
            for j in peer["justifications"]:
                top_q_justifications[j] = top_q_justifications.get(j, 0) + 1

        gap_practices = [
            GapPractice(practice=j, peer_count=cnt, evidence_source="public_signal")
            for j, cnt in sorted(top_q_justifications.items(), key=lambda kv: -kv[1])
            if j not in target_justifications
        ][:3]

        # target_percentile: fraction of peers scoring BELOW the prospect.
        # 0.0 = prospect is lowest-scoring; 1.0 = highest.
        target_score_val = target_maturity.score if target_maturity else 0
        rank = (
            sum(1 for p in peer_scores if p["score"] < target_score_val)
            / max(len(peer_scores), 1)
        )

        attrs["peer_count"] = len(peer_scores)
        attrs["top_q_threshold"] = top_q
        attrs["target_score"] = target_score_val

        return CompetitorGapBrief(
            crunchbase_id=crunchbase_id,
            sector=sector,
            target_score=target_maturity.score if target_maturity else None,
            target_confidence=target_maturity.confidence if target_maturity else None,
            peer_count=len(peer_scores),
            sector_mean_score=round(mean(scores_only), 2) if scores_only else None,
            top_quartile_threshold=top_q,
            target_percentile=round(rank, 2),
            gap_practices=gap_practices,
            top_quartile_peers=top_quartile,
            caveats=[
                "Scores are public-signal estimates. Quiet-but-sophisticated companies score low.",
                "Top-quartile practice may not be a bad thing to not-do; assess context.",
            ],
        )


def _top_quartile_threshold(scores: list[int]) -> int:
    if not scores:
        return 3
    if len(scores) < 4:
        return max(scores)
    q = quantiles(scores, n=4)
    return int(round(q[-1]))
