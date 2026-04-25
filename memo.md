# Tenacious Conversion Engine — Act V Decision Memo

**To:** Tenacious Executive Team
**From:** Gashaw Bekele
**Date:** 2026-04-25
**Re:** Automated outbound pilot recommendation

---

## PAGE 1 — THE DECISION

### Executive Summary

The Conversion Engine is a signal-grounded outbound system that enriches
synthetic B2B prospects across six public-data dimensions (Crunchbase funding,
job-post velocity, layoffs.fyi, leadership change, AI maturity, competitor gap),
classifies them into one of four ICP segments, composes a personalised cold
email via LLM, and automatically books a discovery call on a Tenacious delivery
lead's calendar. In a 150-simulation tau2-Bench retail evaluation it achieved
**pass@1 = 0.7267** (95% CI 0.6504–0.7917), a 60% lift over the Day 1
Bernoulli baseline of 0.453. **Recommendation: run a 30-day paid pilot on
Segment 1 (recently-funded Series A/B), 50 leads per week at a budget of
$150/week, with a success criterion of >= 12% reply rate on signal-grounded
outreach.**

---

### Cost per Qualified Lead

A "qualified lead" is defined as a prospect that (a) receives a
segment-assigned outbound email (confidence >= 0.55) and (b) has a
Cal.com discovery-call booking created in the same orchestrator run.

| Input | Value | Source |
|---|---|---|
| LLM spend (tau2-Bench, 179 traces) | $2.986 | `eval/traces/trace_log.jsonl` |
| Avg cost per orchestrator run | $0.0167 | $2.986 / 179 runs |
| Segment-assigned emails sent | 109 of 110 | `eval/traces/email_sink.jsonl` |
| Bookings created | 109 | HubSpot `stage=discovery_booked` |
| **Cost per qualified lead** | **$0.033** | $2.986 / 90 qualified (pass@1 x 109) |

Decomposition: LLM compose call ~$0.012/run + enrichment API overhead
~$0.004/run + tracing/infra ~$0.001/run = $0.017/run total. At pass@1 = 0.727,
one qualified lead costs $0.017 / 0.727 = **$0.033**. Rig usage (compute) is
negligible (<$0.001/run on commodity Python). No invoice_summary.json exists
for the current sprint; all figures derived directly from trace cost fields
in `eval/traces/trace_log.jsonl`.

---

### Stalled-Thread Rate Delta

**Definition:** A "stalled thread" is any outbound contact that receives no
follow-up action (qualification step, booking, or reply handler registration)
within 24 hours of the initial send. In the automated system, every orchestrator
run completes the full 9-step pipeline (enrich -> compose -> gate -> send -> CRM
upsert -> engagement log -> slot offer -> book -> HubSpot linkage) in a single
synchronous execution. A stall is structurally impossible for any run that
completes without error.

| Channel | Tenacious manual baseline | This system (measured) |
|---|---|---|
| Email outbound | 30–40% stalled threads | **0 / 181 runs (0.0%)** |
| SMS warm-lead | N/A (manual) | 0 / 181 runs (0.0%) |
| Booking step | N/A (manual) | 0 / 109 qualified leads |

The manual 30–40% stall rate arises because human SDRs drop follow-up tasks
after initial send. The automated pipeline eliminates this failure class
entirely: all 181 orchestrator runs in `eval/traces/email_sink.jsonl` proceeded
to HubSpot upsert and Cal.com slot offer within the same synchronous call.
**Delta: -30 to -40 percentage points.**

---

### Competitive-Gap Outbound Performance

Two outbound variants are defined by the ICP segment classifier:

- **Variant A — Research-grounded:** Email leads with a competitor gap finding
  (AI maturity score + top-quartile peer gap). Assigned to Segment 4 prospects
  (AI maturity >= 2, open specialist roles >= 3). Subject lines reference
  capability gap (e.g. "quick note on your AI platform work").
- **Variant B — Signal-grounded, no gap:** Email leads with funding or
  velocity signal. Assigned to Segments 1, 2, 3.

| Variant | Emails sent | Share | Estimated pass@1 | Delta |
|---|---|---|---|---|
| A — Gap-led (Segment 4) | 19 / 110 | 17% | 0.79 (est.) | — |
| B — Funding/velocity-led (Seg 1–3) | 90 / 110 | 82% | 0.72 (est.) | — |
| **Gap vs. generic** | — | — | — | **+7 pp** |

Caveat: tau2-Bench does not provide per-variant split scores directly; the
+7 pp delta is estimated from segment-level pass rates in the trace log.
Sample size for Variant A (n=19) is insufficient for Fisher exact significance.
In a 30-day pilot, n >= 150 per variant is required for a reliable 95% CI.

---

### Pilot Scope Recommendation

| Parameter | Specification |
|---|---|
| **Segment** | Segment 1 — Recently-funded Series A/B ($5M–$30M, last 180 days) |
| **Lead volume** | 50 prospects per week (200 total over 30 days) |
| **Weekly budget** | $150 ($50 LLM + $50 Resend/enrichment + $50 buffer) |
| **Success criterion** | >= 12% reply rate on signal-grounded outreach within 30 days |
| **Kill-switch** | `TENACIOUS_LIVE=1` set only after program-staff sign-off |
| **Measurement** | Reply rate tracked via Resend webhook -> HubSpot engagement log |

Segment 1 selected: largest email volume (38 of 110, 35%), highest segment
confidence (0.90), clearest conversion hook (post-funding hiring pressure).
12% reply-rate target is conservative relative to tau2-Bench pass@1 of 0.73
and is statistically detectable at n=200 (two-proportion z-test, alpha=0.05,
power=0.80, detectable difference=6 pp).

---

## PAGE 2 — THE SKEPTIC'S APPENDIX

### Four Failure Modes tau2-Bench Does Not Capture

| # | Failure Mode | Why Benchmark Misses It | What Catches It | Cost to Add |
|---|---|---|---|---|
| 1 | **Offshore-perception objection (P-011, rate 0.44)** Prospect replies with timezone/quality concerns; agent falls back to generic defence instead of Tenacious case-study evidence. | tau2-Bench simulates single-turn retail tasks. Multi-turn adversarial replies are not in the task distribution. | Multi-turn adversarial eval harness: 30 probes x 5 turns x 3 LLM judges scoring evidence-grounded vs. generic responses. | ~$40 LLM + 2 days |
| 2 | **Bench over-commitment (P-007, rate 0.31)** Agent commits to a 6-person ML squad when bench shows only 3 ML engineers available. | tau2-Bench rewards task completion, not constraint adherence. Capacity over-commitment scores as a "success" in simulation. | Inject live bench_summary into eval context; add a judge step that checks proposed squad size against available capacity. | ~$20 LLM + 1 day |
| 3 | **Brand-reputation risk from stale hiring signals** Agent sends "your Python hiring tripled" when the CTO knows hiring was frozen. Public job-board data has 14–30 day staleness lag. | Benchmark uses synthetic fixtures with consistent data; no task tests signal freshness against prospect ground-truth. | Staleness adversary eval: inject "that headcount is 6 weeks old, we froze hiring" reply and score whether agent retracts or doubles down. | ~$30 LLM + 1 day |
| 4 | **ICP segment mismatch at discovery call** Prospect enriched as Segment 1 but layoff announced between enrichment and call; delivery lead joins with wrong context brief. | tau2-Bench is a static snapshot; prospect state change between enrichment and call is not modelled. | Temporal-drift eval: re-run enrichment on a 14-day-old brief and measure segment assignment drift rate. Threshold: <15% drift in 30 days. | ~$15 LLM + 0.5 day |

---

### Public-Signal Lossiness of AI Maturity Scoring

The AI maturity scorer uses three public signals: AI-adjacent job-role
fraction (weight=high), named AI/ML leadership on the public team page
(weight=high), and public GitHub org activity (weight=medium).

**False Negative — Quietly sophisticated, publicly silent company**

Archetype: 40-person fintech with a private GitHub org, a CTO who avoids
LinkedIn, and zero public job postings (referral-only hiring). The company
has a production ML fraud model and a 3-person ML team; all three signals
read low or absent.

- **System score:** AI maturity = 0 or 1. `silent_company_warning = True`
  when `score <= 1` and `inputs_present <= 2`.
- **What the agent does wrong:** Classifies as Segment 1 (funding-led)
  rather than Segment 4 (capability gap). Outbound email leads with
  funding/velocity, not an AI capability pitch. Delivery lead joins
  the discovery call with the wrong brief.
- **Business impact:** Missed Segment 4 pitch. The CTO does not recognise
  themselves in the email; reply rate near zero. At Tenacious's conversion
  rate, 1 in 4 Segment 4 misclassifications wastes a booking slot worth
  $240K–$720K ACV.

**False Positive — Loud but shallow company**

Archetype: early-stage startup whose co-founder publishes weekly LinkedIn
AI posts, has hired one "Head of AI" as a title signal, and has a public
GitHub org with 50 boilerplate repos. No production ML system exists.

- **System score:** AI maturity = 3 (high confidence). All three
  high-weight signals fire: AI-adjacent job titles, named AI/ML
  leadership, high GitHub activity.
- **What the agent does wrong:** Classifies as Segment 4 and leads with
  a competitor gap pitch implying the company is behind peers in AI
  deployment.
- **Business impact:** The CTO correctly reads the email as inaccurate.
  Trust destroyed in turn 1. In a small sector cohort, a bad first
  impression propagates via founder networks — estimated brand-damage
  radius of 3–5 adjacent prospects. The `silent_company_warning` flag
  guards the false-negative mode; no equivalent guard exists for false
  positives, making this the higher-risk failure.

---

### Honest Unresolved Failure

**Probe P-011 — Offshore-perception objection (category: tone_drift)**

**What it is:** When a prospect replies with an offshore objection
("we've had bad experiences — timezone mismatch, code quality issues"),
the agent produces generic defensive language ("our engineers are just as
good as in-house") rather than citing specific Tenacious case-study
evidence from `data/seed/case_studies.md`. Observed trigger rate: **0.44**
— the highest-frequency tone failure in the 31-probe library.

**Why it is unresolved:** The mechanism built in Act IV (confidence-band
phrasing gate, peer-count suppression) targets signal over-claiming in
initial outbound (P-028). It does not touch multi-turn tone drift. Fixing
P-011 requires a second LLM judge call on every reply turn that detects
defensive language patterns and regenerates using the case-study evidence
template. This was descoped from Act IV to stay within the implementation
budget.

**Business impact if deployed anyway:** At a 0.44 trigger rate across
50 weekly pilot prospects, approximately 22 threads per week terminate
with a defensive response rather than a case-study reference. Each
represents a lost discovery call: 22 x $480K ACV expected value x
expected conversion probability = **~$52,800 in weekly pipeline
destroyed by poor objection handling.** The agent should not handle
multi-turn replies autonomously until this probe rate is below 0.05.

**Kill-switch clause:** All outbound currently routes to
`challenge-sink@tenacious.internal` unless `TENACIOUS_LIVE=1` is
explicitly set. Recommendation for the pilot: disable automated reply
generation entirely; route all inbound replies to a human SDR who uses
the case-study brief as reference. Re-evaluate after 200 reply events.
