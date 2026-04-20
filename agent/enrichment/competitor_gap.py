"""Competitor-gap brief builder.

Given a prospect's sector + AI maturity, identify 5–10 top-quartile
sector peers, apply the same AI-maturity scoring, compute the
prospect's rank within the sector distribution, and extract 2–3
practices the top quartile shows that the prospect does not.

Interim: cluster against the in-repo synthetic fixture. Production:
cluster against the full Crunchbase ODM sample.
"""
from __future__ import annotations

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


def build_competitor_gap_brief(crunchbase_id: str) -> dict[str, Any]:
    tracer = get_tracer()
    with tracer.trace("competitor_gap.build", crunchbase_id=crunchbase_id) as attrs:
        target_rec = _load_sample().get(crunchbase_id)
        if not target_rec:
            return {"error": "target not found", "crunchbase_id": crunchbase_id}

        sector = target_rec["sector"]
        peers = [
            r for r in _load_sample().values()
            if r["sector"] == sector and r["crunchbase_id"] != crunchbase_id
        ]
        target_score = score_ai_maturity(crunchbase_id)

        # Score every peer
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

        # Practice gap: practices present in top-quartile peers but NOT in target
        target_justifications = set(target_score.justifications) if target_score else set()
        top_q_justifications: dict[str, int] = {}
        for peer in top_quartile:
            for j in peer["justifications"]:
                top_q_justifications[j] = top_q_justifications.get(j, 0) + 1

        gap_practices = [
            {"practice": j, "peer_count": cnt}
            for j, cnt in sorted(top_q_justifications.items(), key=lambda kv: -kv[1])
            if j not in target_justifications
        ][:3]

        rank = (
            sum(1 for p in peer_scores if p["score"] < (target_score.score if target_score else 0))
            / max(len(peer_scores), 1)
        )

        attrs["peer_count"] = len(peer_scores)
        attrs["top_q_threshold"] = top_q
        attrs["target_score"] = target_score.score if target_score else None

        return {
            "crunchbase_id": crunchbase_id,
            "sector": sector,
            "target": {
                "score": target_score.score if target_score else None,
                "confidence": target_score.confidence if target_score else None,
            },
            "peer_count": len(peer_scores),
            "sector_mean_score": round(mean(scores_only), 2) if scores_only else None,
            "top_quartile_threshold": top_q,
            "target_percentile": round(rank, 2),
            "gap_practices": gap_practices,
            "top_quartile_peers": top_quartile,
            "caveats": [
                "Scores are public-signal estimates. Quiet-but-sophisticated companies score low.",
                "Top-quartile practice may not be a bad thing to not-do; assess context.",
            ],
        }


def _top_quartile_threshold(scores: list[int]) -> int:
    if not scores:
        return 3
    if len(scores) < 4:
        return max(scores)
    q = quantiles(scores, n=4)
    return int(round(q[-1]))
