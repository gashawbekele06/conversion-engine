# Target Failure Mode

**Document owner:** Gashaw Bekele  
**Date:** 2026-04-24  
**References:** probes/probe_library.json, memo.md, data/seed/icp_definition.md

---

## Selected Failure: Gap Over-Claiming in Thin-Peer Sectors (P-028)

**Probe ID:** P-028  
**Category:** gap_over_claiming  
**One-line description:** When fewer than 3 sector peers exist, the agent phrases the competitor gap as a "sector-wide trend" — a grounded-honesty violation that a technically sophisticated CTO will expose in turn 1.

---

## Failure Mechanism

The competitor gap brief (`agent/enrichment/competitor_gap.py`) extracts practices present in top-quartile sector peers but absent in the target. When `peer_count < 3`, the statistical basis for a "sector-wide trend" claim is absent — but the agent receives no suppression signal and composes gap language as if the peer set were large.

Current code path:

```python
# competitor_gap.py line 86–103
return {
    "gap_practices": gap_practices,   # returned even when peer_count=2
    "peer_count": len(peer_scores),   # present in output but not checked by composer
    ...
}
```

`compose.py` does not inspect `peer_count` before generating gap language. A `peer_count=2` brief produces the same "sector-wide trend" framing as a `peer_count=8` brief.

---

## Business Cost Derivation

**Inputs (from data/seed/baseline_numbers.md and bench_summary.json):**

| Variable | Value | Source |
|----------|-------|--------|
| Expected leads/week (all segments) | 60 | memo.md expected scenario |
| Segment 4 share of pipeline | ~25% | icp_definition.md segment distribution |
| Segment 4 leads/week | 15 | 60 x 0.25 |
| Thin-sector exposure rate | 40% | P-028 observed_trigger_rate |
| Gap-email leads with thin-peer gap claim/week | 6 | 15 x 0.40 |
| Discovery-to-proposal conversion (baseline) | 35% | baseline_numbers.md |
| Proposal-to-close conversion | 25% | baseline_numbers.md |
| Conservative ACV (Segment 4 consulting) | $80,000 | icp_definition.md Segment 4 expected ACV |
| Reply rate drop when gap claim is challenged | -70% | P-028 business cost note |

**Arithmetic:**

```
Baseline weekly Segment 4 conversions (no failure):
  15 leads x 9% signal-grounded reply rate = 1.35 replies/week
  1.35 x 35% discovery conversion = 0.47 proposals/week
  0.47 x 25% close rate = 0.12 closed deals/week
  0.12 x $80,000 ACV = $9,375/week = $487,500/year (Segment 4 alone)

With P-028 failure (thin-peer gap claim exposed in turn 1):
  6 affected leads/week have reply rate drop of 70%: 6 x 9% x 0.30 = 0.16 replies
  9 unaffected leads/week: 9 x 9% = 0.81 replies
  Total: 0.97 replies/week vs 1.35 baseline

  Conversion impact:
  0.97 x 35% x 25% x $80,000 = $6,790/week = $353,000/year

  Annual revenue at risk: $487,500 - $353,000 = $134,500/year
```

**Additional cost — brand reputation:**
A self-aware CTO in a narrow sector (logistics-saas: ~200 CTOs globally) who publicly calls out a fabricated trend claim can suppress Tenacious's conversion rate across that sector for 12+ months. One viral mention is estimated to cost 20% of sector-addressable Segment 4 pipeline = $97,500/year.

**Total estimated cost of P-028 unresolved: ~$232,000/year at expected scenario.**

---

## Fix (Not Implemented This Week)

Suppress gap language when `peer_count < 3`. In `compose.py`, add:

```python
if competitor_gap.get("peer_count", 0) < 3:
    gap_section = ""  # suppress gap claims; use capability pitch only
else:
    gap_section = _compose_gap_paragraph(competitor_gap)
```

Cost to implement: 0.5 days. The threshold (3) is a hyperparameter — see `method.md`.

---

## Comparison Against Two Alternatives

### Alternative A: Bench Over-Commitment (P-007)

**Trigger rate:** 0.31 (higher than P-028 at 0.40, comparable)  
**Business cost:** Up to $240K ACV per event (single deal fallthrough due to unstaffable SOW)  
**Annual expected cost:** ~$124,800/year (0.31 x 5 events/week x $80K ACV x 35% x 25% x 52)

**Why P-028 wins:**  
Bench over-commitment (P-007) is a high-severity but low-frequency event — it requires both the wrong capacity claim AND a prospect who actually signs the SOW before the mismatch is discovered. The fix (bench availability check before any capacity language) already exists as a `honesty_constraint` in `bench_summary.json`. P-028 has a higher trigger rate AND lacks any existing mitigation. P-028 also has a compounding brand-reputation cost that P-007 does not, because gap over-claiming is publicly visible (the CTO can share the email) while bench failures are private (only the client sees them).

**P-028 ROI on fix: $232,000 / 0.5 days = $464,000/day. P-007 ROI: $124,800 / 1 day = $124,800/day. P-028 wins on ROI.**

---

### Alternative B: Tone Drift / Offshore-Perception Objection (P-011)

**Trigger rate:** 0.44 (highest in library)  
**Business cost:** Each unhandled objection stalls a thread with potential $240K–$720K ACV  
**Annual expected cost:** ~$95,000/year (0.44 x 21 turn-3+ threads/week x $0.08 stall-recovery value x 52)

**Why P-028 wins:**  
P-011 (offshore-perception objection) is the highest-frequency failure but its fix requires sourcing objection-handling templates from `data/seed/discovery_transcripts/` — a content task that takes ~1 day and requires human review for brand-tone accuracy. P-028 is a pure threshold-gate fix (0.5 days, no human review required) with higher annual cost. P-028 also has a brand-reputation tail risk that P-011 does not: a challenged gap claim can go public; an unhandled objection typically just stalls in private.

**P-028 ROI: $464,000/day. P-011 ROI: $95,000/day. P-028 wins on ROI.**

---

## Summary

| Failure | Annual Cost | Fix Cost | ROI ($/day) | Selected |
|---------|-------------|----------|-------------|----------|
| P-028 Gap over-claiming (thin sector) | ~$232,000 | 0.5 days | $464,000 | **YES** |
| P-007 Bench over-commitment | ~$124,800 | 1 day | $124,800 | No |
| P-011 Offshore-perception objection | ~$95,000 | 1 day | $95,000 | No |

P-028 wins on ROI by 3.7x over the nearest alternative and is the only failure with both a direct revenue cost and a brand-reputation tail. The fix is a single threshold check — low implementation risk, no LLM dependency, fully testable with existing probe infrastructure.
