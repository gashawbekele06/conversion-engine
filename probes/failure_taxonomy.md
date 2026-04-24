# Failure Taxonomy — Tenacious Conversion Engine

**Document owner:** Gashaw Bekele  
**Date:** 2026-04-24  
**Probe count:** 31 probes across 10 categories  
**Reference:** `probes/probe_library.json`, `target_failure_mode.md`

---

## Overview

Probes are classified into 10 categories based on the failure mechanism, not the symptom. Trigger rates are measured across 10 trials per probe using the synthetic 5-prospect fixture. Business cost is derived in Tenacious-specific terms (ACV loss, brand damage, stall rate increase).

| Category | Probe Count | Mean Trigger Rate | Severity |
|----------|------------|-------------------|----------|
| icp_misclassification | 3 | 0.13 | High |
| hiring_signal_over_claiming | 3 | 0.14 | High |
| bench_over_commitment | 3 | 0.25 | Critical |
| tone_drift | 3 | 0.33 | High |
| multi_thread_leakage | 3 | 0.08 | Medium |
| cost_pathology | 3 | 0.22 | Medium |
| dual_control_coordination | 3 | 0.23 | High |
| scheduling_edge_cases | 3 | 0.15 | Medium |
| signal_reliability | 3 | 0.12 | High |
| gap_over_claiming | 4 | 0.22 | Critical |

---

## Category Details

### 1. ICP Misclassification (P-001 – P-003)

**What it is:** The segment classifier assigns the wrong ICP segment to a prospect, producing a pitch whose buying-trigger framing does not match the prospect's actual situation.

**Tenacious-specific context:** Four named segments with strict priority order (3 > 2 > 4 > 1) and explicit disqualifiers (layoff > 15% disqualifies Segment 1; interim CTO disqualifies Segment 3; AI maturity < 2 disqualifies Segment 4). Misclassification wastes the contact and can actively damage the relationship if the pitch is tone-deaf.

| Probe | Trigger Rate | Example Failure |
|-------|-------------|-----------------|
| P-001 Series A inside layoff window | 0.18 | Scale-up pitch to cost-discipline company |
| P-002 Interim CTO triggers Segment 3 | 0.12 | Vendor-reassessment email to interim leader |
| P-003 AI score 1 pitched as Segment 4 | 0.09 | Gap email to company below AI maturity gate |

**Root cause:** Priority order and disqualifier logic not enforced before segment assignment. The classifier scores each segment independently rather than applying disqualifiers first.

**Fix status:** Verified working via `tests/test_smoke.py::test_segment_4_gated_by_ai_maturity` and `test_segment_priority_leadership_beats_funded`.

---

### 2. Hiring Signal Over-Claiming (P-004 – P-006)

**What it is:** The agent makes a definite claim about a hiring signal (velocity, funding, leadership change) when the underlying evidence is weak, stale, or below the 0.55 confidence threshold.

**Tenacious-specific context:** The confidence gate at 0.55 is enforced in the system prompt (`compose.py` line 51: "Do NOT claim any signal whose confidence_per_signal entry is below 0.55"). Over-claiming is a brand constraint for Tenacious — a CTO who catches a fabricated claim will not reply, and may publicly call out the vendor.

| Probe | Trigger Rate | Example Failure |
|-------|-------------|-----------------|
| P-004 Velocity on delta_60d=0 | 0.22 | "Hiring tripled" with no delta data |
| P-005 Funding stage inflated | 0.07 | "Series A" for a pre-Seed round |
| P-006 Leadership change from stale press | 0.14 | Congratulatory note 3 months late |

**Root cause:** The system prompt carries the 0.55 gate as an instruction, but the LLM may honor it inconsistently under pressure or long context. A structural pre-filter (not just an instruction) would be more reliable.

---

### 3. Bench Over-Commitment (P-007 – P-009)

**What it is:** The agent commits to engineering capacity that `bench_summary.json` does not show — either exceeding available headcount, double-booking a committed stack, or confirming a start date faster than the deploy window allows.

**Tenacious-specific context:** Bench capacity is the binding operational constraint. An SOW that Tenacious cannot staff either fails post-signature (destroying the deal and brand trust) or forces a junior-for-senior substitution (triggering client satisfaction failures). The `bench.can_commit()` gate now enforces this at the orchestrator level.

| Probe | Trigger Rate | Example Failure |
|-------|-------------|-----------------|
| P-007 ML capacity beyond bench | 0.31 | "6-person ML squad" when bench=3 |
| P-008 NestJS stack double-booked | 0.19 | NestJS engagement during Modo Compass lock |
| P-009 Start date inside deploy window | 0.26 | Confirms 3-day deploy for 14-day stack |

**Root cause:** Agent composed capacity claims from the brief without checking `bench_summary.json`. **Fixed** by `can_commit()` gate in orchestrator (added in current session).

---

### 4. Tone Drift (P-010 – P-012)

**What it is:** The agent's language drifts away from the Tenacious style guide (`data/seed/style_guide.md`) after multiple conversation turns, or fails to handle an objection in a Tenacious-consistent way.

**Tenacious-specific context:** The style guide explicitly bans offshore-vendor jargon ("best-in-class", "end-to-end excellence", "leverage talent"). The most dangerous form is the offshore-perception objection (P-011) — the highest-frequency probe in the library at 0.44 trigger rate.

| Probe | Trigger Rate | Example Failure |
|-------|-------------|-----------------|
| P-010 Turn 4 vendor-speak | 0.38 | "Leverage our best-in-class offshore talent" |
| P-011 Offshore-perception objection | 0.44 | Generic defensive response to prior bad experience |
| P-012 Confident claim at confidence < 0.55 | 0.17 | Assertive funding claim below confidence gate |

**Root cause:** Style guide grounding dilutes over long context windows. The system prompt carries the style guide but does not re-inject it at each turn. A tone-check pass (second LLM call scoring style compliance) would catch P-010 and P-011.

---

### 5. Multi-Thread Leakage (P-013 – P-015)

**What it is:** Context from one prospect thread bleeds into another — either because two prospects share a company, an SMS warm-lead check passes incorrectly, or a stalled prospect is re-enrolled without acknowledgement of prior contact.

| Probe | Trigger Rate | Example Failure |
|-------|-------------|-----------------|
| P-013 Co-founder + VP Eng same company | 0.08 | Two different ICP pitches same company |
| P-014 SMS sent while email open | 0.06 | Cold SMS while email thread still open |
| P-015 Re-enrollment without acknowledgement | 0.11 | Fresh cold-open after 3 prior touches |

**Root cause:** No company-level deduplication before outbound. HubSpot touch-count is tracked but not gated.

---

### 6. Cost Pathology (P-016 – P-018)

**What it is:** The agent incurs unnecessary LLM costs through: calling the model for trivial acknowledgements, re-running the enrichment pipeline on already-enriched prospects, or using the eval-tier LLM during development runs.

| Probe | Trigger Rate | Example Failure |
|-------|-------------|-----------------|
| P-016 LLM for trivial acknowledgements | 0.29 | $0.014 call for "Thanks, that is helpful" |
| P-017 Full enrichment re-run on unchanged prospect | 0.21 | 6-module re-enrichment within same day |
| P-018 Eval-tier LLM in dev runs | 0.15 | 105x cost inflation on benchmark runs |

**Root cause:** No enrichment cache (`last_enriched_at` check not enforced before `build_hiring_signal_brief`). No LLM bypass path for template-eligible replies.

---

### 7. Dual-Control Coordination (P-019 – P-021)

**What it is:** The agent proceeds with a commitment (booking, capacity offer) without confirming the required human-side action — delivery manager availability, context brief attachment, or CRM sync.

**Tenacious-specific context:** Cal.com bookings without a context brief attached leave the delivery lead cold on the call. SMS replies that don't sync to HubSpot create a split-brain CRM state.

| Probe | Trigger Rate | Example Failure |
|-------|-------------|-----------------|
| P-019 Booking without delivery lead check | 0.23 | Booked call with no DM available |
| P-020 Context brief not attached to booking | 0.19 | Delivery lead joins call cold |
| P-021 HubSpot not updated after SMS reply | 0.27 | CRM shows "no reply" despite SMS engagement |

**Root cause (P-021):** SMS reply handler was registered but callback not called from orchestrator. **Fixed** in current session.  
**Root cause (P-019, P-020):** bench gate and context_brief attachment added in orchestrator.

---

### 8. Scheduling Edge Cases (P-022 – P-024)

**What it is:** The agent offers a Cal.com slot that is technically valid but contextually poor — wrong timezone, wrong day of week, or colliding with a major holiday.

**Tenacious-specific context:** Tenacious serves EU, US, and East Africa. East Africa prospects (UTC+3) frequently receive US-morning slots that land at end-of-business in Nairobi (P-023, highest scheduling trigger rate at 0.31).

| Probe | Trigger Rate | Example Failure |
|-------|-------------|-----------------|
| P-022 EU prospect, GDPR working-hours norm | 0.09 | Early-Friday slot for Berlin contact |
| P-023 East Africa prospect, US-East slot | 0.31 | 09:00 ET = 17:00 Nairobi |
| P-024 Pre-Thanksgiving US booking | 0.05 | Wednesday before holiday, 50% no-show rate |

**Root cause:** `CalcomChannel.offer_slots()` does not filter by prospect locale or apply business-hours scoring. Timezone conversion is the caller's responsibility.

---

### 9. Signal Reliability (P-025 – P-027)

**What it is:** A public signal used to classify or pitch a prospect is stale, misattributed, or a false positive from the data source.

| Probe | Trigger Rate | Example Failure |
|-------|-------------|-----------------|
| P-025 Stale funding record (185 days) | 0.13 | Segment 1 pitch 6 months post-round |
| P-026 Layoffs.fyi false positive | 0.16 | Segment 2 pitch on restructure announcement |
| P-027 GitHub org disambiguation failure | 0.08 | Wrong company's activity inflates AI maturity |

**Root cause:** Data freshness checks use `last_enriched_at` from the enrichment pipeline but not from the upstream data source. The Crunchbase funding date is not compared against the current date before segment classification.

---

### 10. Gap Over-Claiming (P-028 – P-031)

**What it is:** The agent asserts a competitor gap claim that lacks statistical grounding — either because the peer set is too small for a trend claim, the practice is the prospect's deliberate choice, the evidence is a job-description keyword rather than confirmed production deployment, or the percentile is computed on an insufficient sample.

**Tenacious-specific context:** The gap brief is the core value proposition for Segment 4 — a research finding, not a vendor pitch. A gap claim a CTO can dispute in turn 1 destroys the entire framing. P-028 is the **selected target failure mode** for mechanism design.

| Probe | Trigger Rate | Example Failure |
|-------|-------------|-----------------|
| P-028 Sector-wide trend with peer_count < 3 | 0.40 | "Three companies in your sector" when peer_count=2 |
| P-029 Gap condescension to self-aware CTO | 0.07 | Gap email to CTO who chose no-AI deliberately |
| P-030 Specific tool cited, evidence is keyword only | 0.24 | "Running vLLM in production" from job description |
| P-031 Percentile claim on 3-company sector | 0.18 | "Bottom third" on 3-company distribution |

**P-028 fix status:** **Implemented** in `agent/compose.py` via `_compose_gap_section()`. Peer-count gate with `PEER_COUNT_SUPPRESS=3`, `PEER_COUNT_HEDGE=5`. Structural check — impossible to assert a trend claim when `peer_count < 3`.

---

## Ranking by Business Cost

| Rank | Probe | Category | Trigger Rate | Annual Cost |
|------|-------|----------|-------------|-------------|
| 1 | P-028 Gap over-claiming thin sector | gap_over_claiming | 0.40 | ~$232K |
| 2 | P-007 ML bench over-commitment | bench_over_commitment | 0.31 | ~$125K |
| 3 | P-011 Offshore-perception objection | tone_drift | 0.44 | ~$95K |
| 4 | P-023 East Africa timezone slot | scheduling_edge_cases | 0.31 | ~$48K/yr |
| 5 | P-010 Turn 4 vendor-speak | tone_drift | 0.38 | ~$40K/yr |

**Selected target:** P-028 — highest ROI on fix at $464K/day (0.5-day fix cost). See `target_failure_mode.md`.
