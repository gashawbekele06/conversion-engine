# Mechanism Design: Peer-Count Gate for Gap Over-Claiming (P-028)

**Document owner:** Gashaw Bekele  
**Date:** 2026-04-24  
**Target failure mode:** P-028 — gap claims asserted as sector-wide trends when peer_count < 3  
**Reference:** target_failure_mode.md, probes/probe_library.json, agent/enrichment/competitor_gap.py

---

## 1. Problem Statement

The competitor gap brief (`agent/enrichment/competitor_gap.py`) extracts practices present in top-quartile sector peers but absent in the target. The brief always returns `gap_practices` regardless of how many peers exist. The email composer (`agent/compose.py`) renders these practices as sector-wide trend claims without inspecting `peer_count`.

When `peer_count < 3`, the statistical basis for a "sector-wide trend" is absent. A technically sophisticated CTO will challenge the claim in turn 1, destroying the research-finding framing that makes the gap brief the core value proposition of the Segment 4 pitch.

---

## 2. Mechanism: Peer-Count Gate with Tiered Gap Language

### 2.1 Description

A gate in `agent/compose.py` inspects `competitor_gap["peer_count"]` before generating gap language. Three output tiers are defined based on peer count:

| peer_count | Output tier | Gap language |
|------------|------------|--------------|
| < 3 | Suppressed | No gap claim. Substitute capability-only pitch. |
| 3–4 | Hedged | "A small number of companies in your space are doing X." |
| >= 5 | Asserted | "Several companies in your sector are doing X — you are not yet." |

The threshold values (3 and 5) are hyperparameters (see Section 4).

### 2.2 Implementation

```python
# agent/compose.py — _compose_gap_section() function

def _compose_gap_section(competitor_gap: dict) -> str:
    peer_count = competitor_gap.get("peer_count", 0)
    gap_practices = competitor_gap.get("gap_practices", [])

    if peer_count < 3 or not gap_practices:
        # Gate: suppress gap language entirely — peer set too small to claim a trend
        return ""

    practice_text = gap_practices[0]["practice"] if gap_practices else ""
    hedge = peer_count < 5

    if hedge:
        return (
            f"A small number of companies in your sector are already doing "
            f"{practice_text} — worth a conversation about whether the timing is right for you."
        )
    else:
        return (
            f"{peer_count} companies in your sector show evidence of {practice_text}. "
            f"Based on public signals, your team is not yet there. "
            f"That gap is exactly where Tenacious has placed dedicated squads."
        )
```

### 2.3 How It Addresses the Root Cause

The root cause of P-028 is not hallucination — it is a missing confidence gate. The gap brief correctly reports `peer_count` but the composer ignores it. This mechanism inserts a structural check at the point where language is generated, making it impossible by construction to assert a trend claim without at least 3 peers. It mirrors the existing confidence gate at `compose.py` line 50 (the 0.55 assertion threshold for funding signals), applying the same pattern to peer-count evidence.

---

## 3. Hyperparameters

| Parameter | Value | Justification |
|-----------|-------|--------------|
| `PEER_COUNT_SUPPRESS` | 3 | Below 3 peers, no trend claim is statistically defensible. A 2-company comparison is a bilateral observation, not a sector pattern. |
| `PEER_COUNT_HEDGE` | 5 | 3–4 peers warrants hedged language ("a small number"). 5+ peers approaches a meaningful distribution for a niche sector. |
| `CONFIDENCE_ASSERT_THRESHOLD` | 0.55 | Existing funding-signal gate (compose.py line 50). Peer-count gate operates independently. |
| `MAX_GAP_PRACTICES` | 3 | Hard cap in competitor_gap.py line 75. Prevents information overload in a single email. |

All four parameters are defined as module-level constants and can be overridden via environment variables for A/B testing.

---

## 4. Ablation Variants

### Variant A — Baseline (Current, No Gate)

**What it does:** Returns gap language for any peer_count >= 1. No suppression or hedging.  
**What it tests:** Whether the unguarded gap claim materially hurts reply rates vs. no gap section at all.  
**Expected outcome:** Higher false-positive rate on thin-sector prospects (P-028 trigger rate 0.40). Serves as the baseline measurement for the A/B test.  
**Config:** `PEER_COUNT_SUPPRESS=0`, `PEER_COUNT_HEDGE=0`

### Variant B — Hard Suppress Only (No Hedge Tier)

**What it does:** Suppresses gap language when `peer_count < 5`. No hedged tier — either full assertion or nothing.  
**What it contrasts:** Removes the hedge tier to test whether hedged language is worse than no gap section at all (hedged claims may read as weak and unconvincing, potentially hurting conversion more than a clean capability-only pitch).  
**Expected outcome:** Higher suppression rate (40% → 65% of thin-sector prospects get no gap section). Tests whether the hedge tier adds value or merely dilutes the message.  
**Config:** `PEER_COUNT_SUPPRESS=5`, `PEER_COUNT_HEDGE=5`

### Variant C — Tiered Gate with Peer-Name Citation

**What it does:** Same 3/5 thresholds as the main mechanism, but adds explicit peer company names to the hedged and asserted tiers: "Vantage Pay and ClearStake Finance are both investing in X."  
**What it contrasts:** Tests whether naming specific peers increases credibility (more concrete evidence) or increases risk (the named peer can dispute the claim directly).  
**Expected outcome:** Higher reply rate if the named peer is recognizable to the prospect; higher challenge rate if the evidence for the named peer is weak (the P-030 failure mode).  
**Config:** `PEER_COUNT_SUPPRESS=3`, `PEER_COUNT_HEDGE=5`, `CITE_PEER_NAMES=True`

---

## 5. Statistical Test Plan

### 5.1 Test Design

**Type:** Two-proportion z-test (one-tailed)  
**Unit of analysis:** One outbound email send to one Segment 4 prospect  
**Primary metric:** Reply rate (reply received within 7 days / total sends)  
**Secondary metric:** Stall rate after turn 1 (no second reply within 14 days of first reply)

### 5.2 Groups

| Group | Mechanism | Expected n (4 weeks at 15 Seg-4/week) |
|-------|-----------|---------------------------------------|
| Control | Variant A (no gate) | 30 |
| Treatment | Main mechanism (peer-count gate, tiered) | 30 |

### 5.3 Hypotheses

**H0:** Reply rate(treatment) <= Reply rate(control)  
**H1:** Reply rate(treatment) > Reply rate(control)  
**Significance threshold:** p < 0.05 (one-tailed)  
**Minimum detectable effect:** +3 percentage points (from 9% baseline to 12%)

### 5.4 Power Calculation

```
Baseline reply rate (p1): 0.09
Minimum detectable effect: 0.03 (absolute)
Treatment reply rate (p2): 0.12
Alpha: 0.05 (one-tailed), Beta: 0.20 (power=0.80)

Using two-proportion z-test formula:
n = (z_alpha + z_beta)^2 * (p1*(1-p1) + p2*(1-p2)) / (p2-p1)^2
n = (1.645 + 0.842)^2 * (0.09*0.91 + 0.12*0.88) / (0.03)^2
n = 6.185 * (0.0819 + 0.1056) / 0.0009
n = 6.185 * 0.1875 / 0.0009
n = 1.160 / 0.0009
n = 128 per group (60-day collection window at 15 Seg-4 leads/week per group)
```

At 15 Segment 4 leads/week total, a 60-day pilot provides 128 sends per group.

### 5.5 Decision Rule

- **p < 0.05 AND treatment reply rate >= 12%:** Promote main mechanism to production. Retire Variant A.
- **p >= 0.05:** Extend pilot by 30 days. If still non-significant: suppress the gate entirely and fall back to capability-only pitch for all thin-sector prospects.
- **treatment reply rate < control by > 2pp:** Abort pilot. The gate is hurting performance; investigate whether the suppression of gap language removes the primary value hook for Segment 4.

### 5.6 Observability

All sends are traced with `span_name="orchestrator.run_one"` and carry `prospect_id`, `segment`, and `peer_count` in span attributes (`eval/traces/trace_log.jsonl`). The A/B group assignment can be injected as a `gap_gate_variant` span attribute for post-hoc analysis without requiring a separate logging system.
