# Conversion Engine — Tenacious Consulting & Outsourcing

_Automated B2B outbound pipeline. Week 10 challenge, 10 Academy TRP1, April 2026._

**Final submission:** 2026-04-26 · **Author:** Gashaw Bekele · [@gashawbekele06](https://github.com/gashawbekele06)

---

## What this system does

Given a list of synthetic B2B prospects, the Conversion Engine:

1. **Enriches** each prospect with six public signals (funding, job-post velocity, layoffs, leadership change, AI maturity, competitor gap)
2. **Classifies** each prospect into one of four ICP segments with priority-ordered, disqualifier-enforced rules
3. **Composes** a signal-grounded cold email via LLM, with confidence-gated language and explicit honesty flags
4. **Routes** every message through a kill switch — staff sink by default, never live without explicit opt-in
5. **Upserts** a HubSpot contact record with enrichment provenance and engagement history
6. **Books** a Cal.com discovery call with context brief attached, only after bench-capacity confirmation

Every outbound claim traces to a public signal. Every HubSpot record references a `crunchbase_id` and `last_enriched_at` timestamp. All prospects in this repo are **synthetic**.

A **React + FastAPI dashboard** visualises the full conversion lifecycle in real time — signal briefs, email conversation, HubSpot CRM state, Cal.com booking, and benchmark evidence.

---

## Benchmark scores

| Metric | Value |
|---|---|
| pass@1 | **72.7%** (95% CI: 65.0–79.2%) |
| Simulations | 150 |
| Avg cost / run | **$0.0199** |
| p50 latency | **106 s** |
| p95 latency | 552 s |
| P-028 trigger rate | **0.40 → 0.00** (Fisher exact p = 0.015) |

> **τ²-Bench note:** `tau2_bench` requires Python <3.14; this environment runs 3.14.4. The harness falls back to `llm_backed_v1` (keyword-grounded LLM checks). Full dual-control scoring available once a compatible Python version is available. See [`baseline.md`](baseline.md).

---

## Dashboard

A live React + FastAPI dashboard runs the full pipeline end-to-end and visualises every stage of the conversion lifecycle.

### Start the dashboard

```bash
# Terminal 1 — FastAPI backend (from conversion-engine/ root)
.venv/Scripts/uvicorn dashboard.api:app --reload --port 8000

# Terminal 2 — Vite/React frontend (from dashboard/app/)
cd dashboard/app && npm run dev
```

Open `http://localhost:5173`.

### Dashboard tabs

| Tab | What it shows |
|---|---|
| **Signal & Gap Briefs** | Hiring signal brief with 5 per-signal confidence bars · AI Maturity score (X/3) · Competitor gap brief · P-028 gate badge (suppressed / hedged / full assertion) |
| **Email Conversation** | Send receipt (provider, MSG ID, to/from) · Email body grounded in signal brief · Simulate Prospect Reply button · SMS warm-lead follow-up receipt (Africa's Talking) |
| **HubSpot CRM** | Populated contact record · Lead Status Progression stepper (Attempted → Connected → In Progress) · ⚡ session-current `last_enriched_at` timestamp · Health pills |
| **Cal.com Booking** | Confirmed booking banner · Event type, date, time, attendee · Booking ID · Cal.com confirmation email preview |
| **📈 Benchmark & P-028** | 4 metric tiles (72.7% / 150 / $0.0199 / 106 s) · P-028 delta row (40% → 0%, p=0.015) · Ablation table · Evidence graph (15 traceable claims) |

### Journey Banner

The 6-stage banner at the top of the dashboard advances as the pipeline runs:

```
Prospect Selected → Brief Generated → Email Sent → Prospect Replied → Qualified → Discovery Call Booked
```

Each stage corresponds to a discrete CRM event written to HubSpot.

### API endpoints

| Endpoint | Description |
|---|---|
| `GET /api/prospects` | All 5 synthetic prospects |
| `GET /api/brief/{crunchbase_id}` | Hiring signal brief (live-generated) |
| `GET /api/gap/{crunchbase_id}` | Competitor gap brief |
| `GET /api/email/{prospect_id}` | Latest email for a prospect |
| `GET /api/hubspot/{email}` | HubSpot contact record |
| `GET /api/calcom/{email}` | Cal.com booking |
| `GET /api/bench` | Benchmark scores |
| `GET /api/ablation` | P-028 ablation results |
| `GET /api/evidence` | Evidence graph (15 claims) |
| `GET /api/run/{prospect_id}` | Run full pipeline (SSE stream) |
| `POST /api/sms-send/{prospect_id}` | Send SMS warm-lead follow-up |

---

## ICP segments

| Segment | Name | Primary signal | Disqualifiers |
|---|---|---|---|
| 1 | `recently_funded_series_ab` | Series A/B, $5M–$30M | layoff >15% within 120d |
| 2 | `mid_market_restructuring` | Layoff within 120d, ≥200 employees | — |
| 3 | `engineering_leadership_transition` | CTO/VP-Eng change within 90d | interim appointment |
| 4 | `specialized_capability_gap` | AI maturity score ≥2 | maturity score <2 |

Priority order: **3 > 2 > 4 > 1**. Confidence < 0.6 → generic exploratory email (abstain from segment-specific pitch).

---

## Architecture

```
 ┌─────────────────────┐   ┌─────────────────────┐   ┌─────────────────────┐
 │ Crunchbase ODM      │   │ layoffs.fyi CSV      │   │ BuiltIn / Wellfound │
 │ (fixture + prod)    │   │ (HTTP + fixture fb)  │   │ (Playwright scrape) │
 └──────────┬──────────┘   └──────────┬───────────┘   └──────────┬──────────┘
            │                         │                           │
 ┌──────────▼─────────────────────────▼───────────────────────────▼──────────┐
 │  Enrichment pipeline  (agent/enrichment/)                                  │
 │  funding.py      ← ICP-filtered, staleness-aware (P-025 mitigation)        │
 │  layoffs.py      ← CC-BY CSV parser + fixture fallback                     │
 │  jobposts.py     ← Playwright scrape + 60d snapshot-delta store            │
 │  leadership.py   ← typed LeadershipSignal, interim-aware                  │
 │  ai_maturity.py  ← 0–3 score + confidence (6 weighted signals)            │
 │  competitor_gap.py ← CompetitorGapBrief dataclass; same scorer for peers  │
 │  brief_generator.py ← HiringSignalBrief with per-signal source/ts/conf    │
 └──────────┬─────────────────────────────────────────────────────────────────┘
            │
 ┌──────────▼─────────────────────────────────────────────────────────────────┐
 │  Agent core  (agent/)                                                       │
 │  compose.py        ← confidence-gated email + P-028 peer-count gate        │
 │  orchestrator.py   ← 9-step pipeline; bench gate; email+SMS reply handlers │
 │  channel_router.py ← explicit state machine (cold→warm_email→warm_sms→    │
 │                       meeting_booked); ChannelState enum + transitions      │
 │  bench.py          ← can_commit() gate before every slot offer             │
 │  kill_switch.py    ← all outbound → staff sink unless TENACIOUS_LIVE=1     │
 └──────────┬─────────────────────────────────────────────────────────────────┘
            │
 ┌──────────▼─────────────────────────────────────────────────────────────────┐
 │  Channels  (agent/channels/)                                                │
 │  email.py    ← Resend / mock; kill-switched                                │
 │  sms.py      ← Africa's Talking / mock; warm-lead gate enforced in code;   │
 │                "email reply before SMS" policy: checks inbox.jsonl first    │
 │  hubspot.py  ← upsert + engagement log + meeting mark                      │
 │  calcom.py   ← slot offer + booking + context brief attachment             │
 └──────────┬─────────────────────────────────────────────────────────────────┘
            │
 ┌──────────▼─────────────────────────────────────────────────────────────────┐
 │  Eval & Tracing                                                             │
 │  eval/tau2_harness.py     ← pass@1 runner with cost + latency capture      │
 │  eval/evidence_graph.py   ← audits 15 claim→trace linkages (0 issues)      │
 │  eval/traces/             ← trace_log.jsonl, email/sms/calcom/hs sinks     │
 │  probes/                  ← 31 adversarial probes, 10 failure categories    │
 └────────────────────────────────────────────────────────────────────────────┘
```

---

## Quick start

```bash
# 1. Clone and install
git clone https://github.com/gashawbekele06/conversion-engine.git
cd conversion-engine
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Required for real LLM calls: OPENROUTER_API_KEY
# Leave TENACIOUS_LIVE unset — all outbound routes to staff sink

# 3. Run all tests (no API keys required)
pytest tests/ -v                            # expect: 69 passed

# 4. Dry run — zero cost, zero LLM calls, all 5 prospects
python -m agent.main dry-run

# 5. Inspect a single prospect's enrichment brief
python -m agent.main enrich prospect_001   # also accepts cb_sample_001

# 6. Full pipeline for one prospect (simulates reply + Cal.com booking)
python -m agent.main run-one prospect_001

# 7. Full pipeline for all 5 prospects
python -m agent.main run-all

# 8. Benchmark (dev slice, 1 trial, ~$0.002)
export OPENROUTER_API_KEY=<key>
python eval/run_baseline.py --slice dev --trials 1 --real

# 9. Inbound webhook server (for real email/SMS reply handling)
python -m agent.main serve --port 8080

# 10. Dashboard — FastAPI backend + React frontend
.venv/Scripts/uvicorn dashboard.api:app --reload --port 8000   # Terminal 1
cd dashboard/app && npm run dev                                 # Terminal 2
# → open http://localhost:5173
```

---

## CLI reference

| Command | Description |
|---|---|
| `dry-run` | All 5 prospects, no LLM cost, kill switch engaged |
| `enrich <id>` | Print hiring-signal brief + competitor gap for one prospect (`prospect_*` or `cb_sample_*`) |
| `run-one <id>` | Full 9-step pipeline for one prospect, simulated reply |
| `run-all` | Full pipeline for all 5 prospects |
| `serve [--host] [--port]` | Start FastAPI inbound webhook server |

---

## Enrichment signals

Each signal carries **source**, **fetched_at** timestamp, and **confidence**. Signals below 0.55 trigger hedged language in the composer; below 0.0 → suppressed.

| Signal | Module | Confidence logic |
|---|---|---|
| Funding | `funding.py` | 0.95 (≤90d) → 0.70 (91–180d) → 0.35 (>180d, P-025 stale); 0.0 if outside ICP range |
| Job velocity | `jobposts.py` | 0.25 (<5 roles) / 0.55 (5–9) / 0.85 (10+); `velocity_label` enum |
| Layoffs | `layoffs.py` | 0.85 if event within 120d window; CC-BY CSV parser with fixture fallback |
| Leadership change | `leadership.py` | 0.9 (confirmed) / 0.5 (interim) / 0.0 (none) |
| AI maturity | `ai_maturity.py` | 0.0–0.4 based on count of 6 weighted public inputs; silent-company warning |
| Competitor gap | `competitor_gap.py` | `CompetitorGapBrief` dataclass; `target_percentile` distribution position |

**60-day velocity delta:** Live Playwright scrapes append a snapshot to `eval/traces/jobpost_snapshots.jsonl`. On the next run, `_compute_delta_60d()` finds the snapshot closest to 60 days ago (±30d tolerance) and computes a real delta. Edge cases: no snapshot → `velocity_label="insufficient_signal"`; negative delta → `"declined"`.

**Layoffs.fyi CSV parsing:** `_parse_layoffs_csv_row()` handles the CC-BY CSV format (optional headcount, percentage as `"15%"` or `"0.15"`). Configure `LAYOFFS_FYI_CSV_URL` in `.env` for production; fixture fallback is automatic in development.

---

## Channel-handoff state machine

`agent/channel_router.py` defines explicit transition rules so channel escalation is never implied:

```
cold_outbound ──email_reply_positive──▶ warm_email ──sms_reply──▶ warm_sms
     │                                      │                         │
     └──email_reply_negative──▶ declined    └──calcom_booked──▶ meeting_booked
                                            └──bench_blocked──▶ bench_blocked
```

`can_send("sms")` returns `False` in `cold_outbound` — SMS is only reachable after an email reply. The SMS warm-lead gate also checks `eval/traces/inbox.jsonl` for prior email replies, enforcing "email reply before SMS" in code, not just documentation.

---

## Known failure modes

31 adversarial probes across 10 categories. See [`probes/failure_taxonomy.md`](probes/failure_taxonomy.md).

| Rank | Probe | Category | Trigger rate (baseline) | Status |
|---|---|---|---|---|
| 1 | P-028 Gap over-claiming, thin sector | `gap_over_claiming` | 0.40 → **0.00** | Fixed |
| 2 | P-007 ML bench over-commitment | `bench_over_commitment` | 0.31 | Fixed (bench gate) |
| 3 | P-011 Offshore-perception objection | `tone_drift` | 0.44 | Open |
| 4 | P-023 East Africa timezone slot | `scheduling_edge_cases` | 0.31 | Open |
| 5 | P-010 Turn-4 vendor-speak | `tone_drift` | 0.38 | Open |

---

## Safety constraints

| Constraint | Enforcement |
|---|---|
| Kill switch defaults closed | `TENACIOUS_LIVE` unset → all outbound to `STAFF_SINK_EMAIL` |
| SMS warm-lead only | `WarmLeadRequired` raised if no prior email or SMS reply found in sink |
| Bench capacity gate | `can_commit()` checked before every Cal.com slot offer |
| Confidence gate at 0.55 | Signals below threshold → hedged language in `compose.py` |
| Peer-count gate (P-028) | `peer_count < 3` → gap section suppressed entirely in composed email |
| No real prospect data | All records in `synthetic_prospects.json` are synthetic |

---

## Directory layout

```
conversion-engine/
├── README.md
├── baseline.md                   ← Act I: τ²-Bench scores + reproducibility checklist
├── method.md                     ← Mechanism design: peer-count gate + 3 ablations
├── target_failure_mode.md        ← P-028 selected, business cost arithmetic
├── memo.md / memo.pdf            ← Act V: two-page decision memo + Skeptic's Appendix
├── ablation_results.json         ← Delta A/B/C with statistical tests (p=0.015)
├── CHANGELOG.md
├── CLAUDE.md                     ← Inheritor context (read this first)
├── requirements.txt
├── .env.example
│
├── agent/
│   ├── config.py                 ← env → Config dataclass
│   ├── kill_switch.py            ← hard-gates all outbound
│   ├── tracing.py                ← JSONL trace sink (Langfuse-compatible)
│   ├── llm.py                    ← OpenRouter + Anthropic SDK + deterministic fallback
│   ├── compose.py                ← signal-confidence-aware composer; P-028 gate
│   ├── bench.py                  ← can_commit() bench-capacity gate
│   ├── channel_router.py         ← ChannelState enum + explicit transition rules
│   ├── orchestrator.py           ← 9-step pipeline; email + SMS reply handlers
│   ├── webhooks.py               ← FastAPI inbound webhook handlers
│   └── main.py                   ← CLI
│
│   ├── channels/
│   │   ├── email.py              ← Resend / mock; kill-switched
│   │   ├── sms.py                ← Africa's Talking / mock; email-reply warm-lead check
│   │   ├── hubspot.py            ← upsert + engagement log + meeting mark
│   │   └── calcom.py             ← slot offer + booking + context brief
│   │
│   └── enrichment/
│       ├── crunchbase.py         ← firmographic lookup (ODM sample)
│       ├── funding.py            ← ICP-filtered, staleness-aware funding signal
│       ├── layoffs.py            ← CC-BY CSV parser + typed LayoffSignal
│       ├── jobposts.py           ← Playwright scrape + 60d snapshot-delta store
│       ├── leadership.py         ← typed LeadershipSignal; interim-aware
│       ├── ai_maturity.py        ← 0–3 score; 6 weighted inputs; silent-company flag
│       ├── competitor_gap.py     ← CompetitorGapBrief dataclass; target_percentile
│       └── brief_generator.py   ← HiringSignalBrief: per-signal source/ts/conf/flags
│
├── data/
│   ├── seed/
│   │   ├── icp_definition.md
│   │   ├── style_guide.md
│   │   ├── bench_summary.json
│   │   ├── pricing.json
│   │   ├── case_studies.md
│   │   ├── hiring_signal_brief.schema.json   ← formal JSON Schema for brief output
│   │   └── competitor_gap_brief.schema.json  ← formal JSON Schema for gap output
│   └── synthetic_prospects.json             ← 5 target prospects + 11 sector peers
│
├── eval/
│   ├── tau2_harness.py           ← pass@1 runner with cost + latency
│   ├── run_baseline.py           ← dev / held-out slice runner
│   ├── evidence_graph.py         ← 15-claim audit (0 issues)
│   ├── score_log.json
│   ├── dev_slice.json            ← 30-task dev partition
│   ├── held_out_slice.json       ← 20-task sealed partition
│   └── traces/
│       ├── trace_log.jsonl       ← all spans (5191+ rows)
│       ├── inbox.jsonl           ← inbound email/SMS replies
│       ├── email_sink.jsonl
│       ├── sms_sink.jsonl
│       ├── jobpost_snapshots.jsonl  ← 60-day velocity snapshot store
│       ├── hubspot_mock.json
│       └── calcom_mock.json
│
├── probes/
│   ├── probe_library.json        ← 31 adversarial probes, 10 categories
│   └── failure_taxonomy.md      ← trigger rates, root causes, fix status, cost ranking
│
└── tests/
    └── test_smoke.py             ← 69 tests, all passing
```

---

## Data-handling policy

| Rule | Enforcement |
|---|---|
| No real Tenacious customer data | Only synthetic fixtures in `data/synthetic_prospects.json` |
| All prospect traffic is synthetic | `synthetic=True` on every channel call; kill switch enforces |
| Kill switch defaults closed | `TENACIOUS_LIVE` unset → `STAFF_SINK_EMAIL` |
| Outputs tagged draft | Every mock payload carries `metadata.draft=true` |
| Seed materials not redistributed | ICP/style/pricing are internal representations only |

---

## Reproducibility

```bash
# Dev baseline (real LLM)
export OPENROUTER_API_KEY=<key>
python eval/run_baseline.py --slice dev --trials 1 --real
# → run_140a8c18  pass@1=0.933  cost=$0.041

# Held-out validation
python eval/run_baseline.py --slice held_out --trials 1 --real
# → run_a12f55d4  pass@1=1.000  cost=$0.023

# Evidence graph audit
python eval/evidence_graph.py eval/traces/evidence_graph.json
# → {"ok": true, "issues": [], "n_claims": 15, "n_traces": 297}

# When Python <3.14 is available — full τ²-Bench dual-control scoring
pip install tau2-bench
python eval/tau2_harness.py --slice held_out --trials 5 --real
```

Results append to `eval/score_log.json` with stable run IDs.

---

## First reads for new contributors

1. [`CLAUDE.md`](CLAUDE.md) — critical constraints, known limitations, run order
2. [`data/seed/icp_definition.md`](data/seed/icp_definition.md) — segment rules and disqualifiers
3. [`agent/kill_switch.py`](agent/kill_switch.py) — the only outbound gate
4. [`target_failure_mode.md`](target_failure_mode.md) + [`method.md`](method.md) — P-028 and the fix
5. [`probes/probe_library.json`](probes/probe_library.json) — all 31 failure modes; read before touching `compose.py`
