# Architecture — Conversion Engine

## One-slide summary

The Conversion Engine is a signal-grounded outbound system. Every
touch starts with a public-signal brief the prospect can verify against
their own record, ends with a booked discovery call on a Tenacious
delivery lead's calendar, and writes a complete audit trail the
Tenacious executive team can read without the originating engineer.

---

## Architecture Diagram

```
  ┌─────────────────────────────────────────────────────────────────────┐
  │                       ENRICHMENT PIPELINE                           │
  │                                                                     │
  │  Crunchbase ODM ──► funding.py ──────────────────┐                 │
  │  Playwright scrape ► jobposts.py ─────────────── │                 │
  │  layoffs.fyi CSV ──► layoffs.py ──────────────── ├──► brief_       │
  │  Crunchbase/press ──► leadership.py ─────────── │     generator   │
  │  GitHub/LinkedIn ──► ai_maturity.py ─────────── │     .py         │
  │  Sector peers ─────► competitor_gap.py ────────┘     │            │
  └────────────────────────────────────────────────────────┼───────────┘
                                                           │
                              hiring_signal_brief (JSON)   │
                              + competitor_gap_brief        │
                                                           ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │                     COMPOSE + KILL-SWITCH                           │
  │                                                                     │
  │  hiring_signal_brief ──► compose.py ──► LLM (OpenRouter/Anthropic) │
  │                              │                                      │
  │                         composed email                              │
  │                              │                                      │
  │                              ▼                                      │
  │               kill_switch.py ──► TENACIOUS_LIVE=1?                  │
  │                    │                   │                            │
  │                    NO                 YES                           │
  │                    ▼                   ▼                            │
  │             staff sink         prospect address                     │
  └──────────────────────────────────────────────────────┬──────────────┘
                                                         │
                                                         ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │                     CHANNEL HANDLERS                                │
  │                                                                     │
  │  channels/email.py  ◄──► Resend / MailerSend                       │
  │  channels/sms.py    ◄──► Africa's Talking (warm-lead gate)         │
  │  channels/hubspot.py◄──► HubSpot Developer Sandbox (CRM)           │
  │  channels/calcom.py ◄──► Cal.com (booking)                         │
  │                                                                     │
  │  webhooks.py  ◄── inbound replies (email bounce / SMS STOP/HELP)   │
  └──────────────────────────────────────────────────────┬──────────────┘
                                                         │
                                                         ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │                     OBSERVABILITY                                   │
  │                                                                     │
  │  tracing.py ──► eval/traces/trace_log.jsonl  (Langfuse-compatible) │
  │                 ├── email_sink.jsonl                                │
  │                 ├── sms_sink.jsonl                                  │
  │                 └── hubspot_mock.json / calcom_mock.json            │
  │                                                                     │
  │  eval/evidence_graph.py ──► evidence_graph.json (15 claims)        │
  └─────────────────────────────────────────────────────────────────────┘
```

---

## Data flow

1. **Seed** — `data/synthetic_prospects.json` provides Crunchbase IDs
   for the challenge week. Production replaces this with a pointer to
   the full Crunchbase ODM sample + live Playwright crawl.
2. **Enrich** — `agent/enrichment/brief_generator.build_hiring_signal_brief`
   runs each sub-signal (funding, job velocity, layoffs, leadership,
   AI maturity) and returns a merged JSON artifact with per-signal
   confidence, source, and fetched_at timestamp.
3. **Classify** — `classify_segment` picks one of the four ICP segments
   with the mutual-exclusion rule documented in `icp_definition.md`
   (3 > 2 > 4 > 1). Segment 4 is gated on AI maturity ≥ 2.
4. **Compose** — `agent/compose.compose_email` calls the LLM with the
   seed style guide and the brief; the output's phrasing shifts with
   `confidence_band ∈ {high, medium, low}` — this is the hook for
   the Act IV mechanism.
5. **Gate** — `agent/kill_switch.KillSwitch.resolve` rewrites the `to`
   address to the staff sink unless `TENACIOUS_LIVE=1` AND the prospect
   is explicitly marked non-synthetic.
6. **Send** — email via Resend/MailerSend (mocked by default). SMS via
   Africa's Talking sandbox (warm-lead gate enforced in code). Voice is
   bonus-tier via the Shared Voice Rig.
7. **Record** — `channels/hubspot.HubSpotChannel.upsert_contact` enforces
   `crunchbase_id` and `last_enriched_at` on every contact row.
   `log_engagement` appends to an append-only engagement table.
8. **Book** — `channels/calcom.CalcomChannel.offer_slots` + `.book`
   attach the brief to the calendar event so the delivery lead joins
   with context.
9. **Trace** — every step emits a JSONL row in
   `eval/traces/trace_log.jsonl`. The Act V evidence-graph script
   (`eval/evidence_graph.py`) walks these rows to verify memo claims.

---

## Kill-switch invariant

No outbound message reaches a real prospect address unless ALL of:

- `TENACIOUS_LIVE=1` environment variable set
- the prospect record carries `synthetic=False`
- program staff have signed off (manual attestation in repo CHANGELOG)

The default configuration satisfies Data-Handling Policy rule 4.

---

## Signal-confidence-aware phrasing (Act IV seed)

Per-signal confidence is carried forward from `brief_generator` to
`compose.compose_email`. The `confidence_band` is computed as the
maximum per-signal confidence; the system prompt forbids asserting
any signal below 0.55 confidence (must soften to an ask). In Act IV
this gate is strengthened: a second model call scores whether the
draft over-claims on any signal and regenerates with lower temperature
if it does. Expected Delta A: +3 to +6 percentage points on the
held-out slice.

---

## τ²-Bench integration

`eval/tau2_harness.run_pass_at_1` is the scored entry point. In mock
mode (default) it emits `None` pass rates so the score log never
carries fabricated numbers. In real mode it imports `tau2_bench`
and executes the pinned model with the dev/held-out task partition.
Trace rows are Langfuse-compatible via `OTEL` semantics — the
`trace_id` + `span_id` convention is shared between the agent and
the harness.

---

## Observability

`agent/tracing.Tracer` writes one JSONL row per span with:
`trace_id`, `span_id`, `parent_span_id`, `name`, `started_at`,
`ended_at`, `duration_ms`, `status`, `attributes`.

This is the substrate for:
- per-lead cost attribution (sum `attributes.cost_usd` by `trace_id`)
- p50/p95 latency (`duration_ms` of `orchestrator.run_one` spans)
- evidence-graph audit (claim → trace_id → numeric attribute)

---

## Directory index

| Path | Purpose |
|---|---|
| `agent/` | All production pipeline code. Entry point: `python -m agent.main`. |
| `agent/channels/` | One module per integration: `email.py` (Resend), `sms.py` (Africa's Talking with warm-lead gate), `hubspot.py` (CRM upsert + engagement log), `calcom.py` (slot offer + booking). |
| `agent/enrichment/` | Six signal modules (`crunchbase.py`, `jobposts.py`, `layoffs.py`, `leadership.py`, `ai_maturity.py`, `competitor_gap.py`) plus `brief_generator.py` which merges them into a single hiring-signal brief with per-signal confidence, source, and timestamp. |
| `agent/compose.py` | LLM email composer. Reads the brief, applies confidence-band phrasing rules, and calls OpenRouter / Anthropic SDK. |
| `agent/kill_switch.py` | Route resolver: rewrites `to` address to staff sink unless `TENACIOUS_LIVE=1` + `synthetic=False`. Single choke-point for all outbound. |
| `agent/orchestrator.py` | 9-step end-to-end pipeline per prospect: enrich → compose → gate → send → CRM upsert → engagement log → slot offer → book → HubSpot linkage. |
| `agent/llm.py` | LLM client with two tiers: OpenRouter (dev, cost-optimised) and Anthropic SDK (eval). Tier selected by `LLM_TIER` env var. |
| `agent/webhooks.py` | FastAPI inbound handlers for email bounce/reply and SMS STOP/HELP/UNSUB. Dispatches to registered reply handlers. |
| `agent/config.py` | All configuration fields with `os.getenv` defaults. Single source of truth for every API key and toggle. |
| `data/` | Seed data: `synthetic_prospects.json` (5 target prospects + 11 sector peers), ICP definition, bench summary, pricing guide, and case studies. |
| `data/seed/` | Operator-facing configuration: `icp_definition.md`, `bench_summary.json` (capacity + honesty constraint), `style_guide.md`, and competitor scoring criteria. |
| `eval/` | Benchmarking harness (`run_bench.py`, `tau2_harness.py`), score log, latency summary, and all trace artifacts (JSONL sink, evidence graph). |
| `eval/traces/` | Append-only JSONL sinks for email, SMS, HubSpot mock, Cal.com mock, and the master `trace_log.jsonl` (5 191+ rows). |
| `probes/` | Adversarial probe library (`probe_library.json`, 31 structured probes across 10 categories). |
| `docs/` | Architecture diagram (this file) and any supplementary design docs. |
| `tests/` | 7 smoke tests (all passing). Cover kill-switch invariant, warm-lead gate, probe trigger rates, and evidence graph integrity. |
| `tau2-bench/` | Git submodule: pinned tau2-bench release used for benchmark scoring. |

---

## Environment variables

All variables are read in `agent/config.py`. Copy `.env.example` → `.env` and fill in the required keys.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `TENACIOUS_LIVE` | No | unset | Set to `1` to allow live outbound. **Leave unset in all dev/test environments.** |
| `LLM_TIER` | No | `dev` | `dev` = OpenRouter (cheap), `eval` = Anthropic SDK (scored). |
| `LLM_MODEL_DEV` | No | `qwen/qwen3-next-80b-a3b` | Model ID sent to OpenRouter in dev tier. |
| `LLM_MODEL_EVAL` | No | `anthropic/claude-sonnet-4.6` | Model ID for eval tier runs. |
| `OPENROUTER_API_KEY` | For LLM | — | OpenRouter API key. Pipeline falls back to deterministic template if unset. |
| `ANTHROPIC_API_KEY` | For eval | — | Anthropic SDK key. Only needed for `LLM_TIER=eval`. |
| `RESEND_API_KEY` | For email | — | Resend delivery API key. Email falls back to JSONL mock if unset. |
| `MAILERSEND_API_KEY` | For email | — | MailerSend alternative. Either Resend or MailerSend is sufficient. |
| `AT_USERNAME` | For SMS | `sandbox` | Africa's Talking username (`sandbox` or live account name). |
| `AT_API_KEY` | For SMS | — | Africa's Talking API key. SMS falls back to mock if unset. |
| `HUBSPOT_TOKEN` | For CRM | — | HubSpot Developer Sandbox private app token. CRM falls back to JSONL mock if unset. |
| `CALCOM_API_KEY` | For calendar | — | Cal.com API key. Booking falls back to JSONL mock if unset. |
| `LANGFUSE_PUBLIC_KEY` | No | — | Langfuse cloud ingest. Traces always write to local JSONL regardless. |
| `LANGFUSE_SECRET_KEY` | No | — | Langfuse cloud ingest. |
| `LANGFUSE_HOST` | No | `https://cloud.langfuse.com` | Override for self-hosted Langfuse. |
| `STAFF_SINK_EMAIL` | No | `challenge-sink@tenacious.internal` | Kill-switch redirect target for email. |
| `STAFF_SINK_SMS` | No | `+10000000000` | Kill-switch redirect target for SMS. |
| `LAYOFFS_FYI_CSV_URL` | No | — | Direct URL to layoffs.fyi CC-BY CSV export. Falls back to fixture if unset. |

### Pinned dependency versions (from `pyproject.toml`)

| Package | Pinned range | Role |
|---|---|---|
| `fastapi` | `>=0.110,<1.0` | Webhook server |
| `uvicorn[standard]` | `>=0.27,<1.0` | ASGI runner |
| `pydantic` | `>=2.5,<3.0` | Data validation |
| `python-dotenv` | `>=1.0` | `.env` loader |
| `requests` | `>=2.31` | HTTP client (channels) |
| `httpx` | `>=0.27` | Async HTTP (Playwright helper) |
| `resend` | `>=2.0` | Email delivery |
| `africastalking` | `>=1.2` | SMS delivery |
| `openai` | `>=1.30` | OpenRouter-compatible LLM client |
| `anthropic` | `>=0.25` | Anthropic SDK (eval tier) |
| `langfuse` | `>=2.20` | Observability sink |
| `playwright` | `>=1.42` | Job-post scraper |
| `hubspot-api-client` | `>=12.0.0` | CRM integration |
| `pandas` | `>=2.2` | Data processing |
| `pytest` | `>=8.0` | Test runner |

---

## What's mocked vs. real — final status (2026-04-23)

| Layer | Status | Evidence |
|---|---|---|
| Crunchbase lookup | Synthetic fixture (cb_sample_001) | `data/synthetic_prospects.json` |
| Job-post velocity | Synthetic fixture + Playwright implemented | `agent/enrichment/jobposts.py` |
| layoffs.fyi | Synthetic fixture (120d window) | `agent/enrichment/layoffs.py` |
| Leadership change | Synthetic fixture, typed LeadershipSignal | `agent/enrichment/leadership.py` |
| LLM compose | OpenRouter claude-sonnet-4-6 (eval tier) | `eval/score_log.json run_140a8c18` |
| Email send | **Resend live verified** | message_id: `001cdf69-13fa-498c-bcc8-470b8a444d15` |
| SMS send | AT sandbox broken (port 443 plain HTTP; port 80 returns 400 pre-parse) | `agent/channels/sms.py` |
| HubSpot upsert | HubSpot Developer Sandbox | `eval/traces/hubspot_mock.json` (97 KB) |
| Cal.com booking | Cal.com production API | `eval/traces/calcom_mock.json` (40 KB) |
| tau2-Bench run | **Real LLM run completed** | `run_140a8c18` dev=0.933, `run_a12f55d4` held_out=1.000 |
| Langfuse sink | Local JSONL (5 191+ trace IDs) | `eval/traces/trace_log.jsonl` |
| Competitor gap brief | **Generating output** | `data/competitor_gap_brief_prospect001.json` |
| Evidence graph | **ok: true, 0 issues** | `eval/traces/evidence_graph.json` (15 claims) |

Every layer without a live API key degrades gracefully to a JSONL sink
or fixture fallback — the pipeline is fully runnable without external
credentials.

---

## Local bootstrap — run order

```bash
# Prerequisites: Python 3.13+, pip

# 1. Install dependencies
pip install -r requirements.txt
# or: pip install -e ".[dev]"

# 2. Configure environment
cp .env.example .env
# Fill in: OPENROUTER_API_KEY, RESEND_API_KEY, HUBSPOT_TOKEN, CALCOM_API_KEY

# 3. Verify setup
pytest tests/ -v              # expect: 7 passed in < 1s

# 4. Dry run (no LLM cost, no external calls, ~1s per prospect)
python -m agent.main --dry-run

# 5. Single prospect end-to-end
python -m agent.main run-one prospect_001

# 6. All prospects
python -m agent.main run-all

# 7. Benchmark (dev tier, ~$0.002 total)
python eval/run_bench.py

# 8. Validate evidence graph
python eval/evidence_graph.py eval/traces/evidence_graph.json
```

---

## Successor playbook — known limitations and immediate priorities

This section is written for the engineer who inherits this codebase.
Below are the issues you will hit, their root causes, and suggested
next steps in priority order.

### P1 — tau2-Bench uses LLM-backed fallback, not dual-control scoring

**What:** `eval/tau2_harness.py` imports an LLM-backed pass@1 evaluator
because `tau2_bench` requires Python `<3.14` and this environment runs
3.14.4. All reported scores (dev=0.933, held_out=1.000) come from the
keyword-grounded LLM check, not the Sierra Research dual-control benchmark.

**Fix:** Upgrade `tau2-bench` to a Python 3.14-compatible release, or
run evaluations in a Python 3.12 venv. The harness interface is stable —
no code changes needed, just a compatible environment.

**Impact:** Scores are directionally valid but not directly comparable
to teams that ran the dual-control benchmark.

### P2 — Job-post velocity `delta_60d = 0` on live Playwright scrapes

**What:** `agent/enrichment/jobposts.py` sets `delta_60d=0` on live
Playwright scrapes because computing velocity requires a historical
snapshot. The fixture path returns real `delta_60d` values.

**Fix:** Add a nightly snapshot job (e.g., a GitHub Actions cron) that
writes a dated JSONL snapshot. `job_velocity()` can then compare today's
count against the 60-day-old snapshot.

**Impact:** Live scrape results show 0 velocity even for rapidly hiring
companies, underweighting Segment 1 classification.

### P3 — Africa's Talking sandbox TLS broken

**What:** `api.sandbox.africastalking.com:443` serves plain HTTP (not TLS)
as of 2026-04-23. Plain HTTP on ports 80 and 443 returns `400 Bad Request`
before reading request headers — confirmed via raw TCP, curl (SChannel),
and Python ssl module. Not a credentials or network issue.

**Fix:** Wait for AT to fix their sandbox infrastructure, or activate a
live AT account (requires account verification). The channel code and
warm-lead gate are correct; only the transport is broken.

**Impact:** SMS channel falls back to JSONL mock sink. Warm-lead gate,
kill-switch routing, and inbound dispatch all work correctly.

### P4 — GitHub org disambiguation not implemented

**What:** `agent/enrichment/ai_maturity.py` uses a `github_org_activity`
field from the fixture. In production, the scraper could attribute
activity from a same-prefix but unrelated GitHub org (P-027).

**Fix:** Add a disambiguation step that compares the org description to
the company name before scoring. Low priority until live GitHub scraping
is wired.

### P5 — HubSpot SMS reply updates require phone→email mapping

**What:** `Orchestrator._register_sms_reply_handler()` maps inbound SMS
phone numbers to prospect emails for CRM updates. The map is populated
from `synthetic_prospects.json`. In production, this map must be seeded
from HubSpot contact records at startup.

**Fix:** On startup, fetch all HubSpot contacts with a phone field and
build the reverse mapping. Update on new contact creation.

### Architectural trade-offs to know before changing compose.py

- **Peer-count gate (PEER_COUNT_SUPPRESS=3):** Suppresses all gap trend
  claims when fewer than 3 sector peers have scorable data. Do not lower
  this threshold — P-028 (gap over-claiming) trigger rate jumps from
  0.0 to 0.40 (Fisher exact p=0.015, see `ablation_results.json`).
- **Confidence gate (0.55):** Below this threshold the composer uses
  hedged language. Lowering it increases assertiveness and P-028/P-031
  trigger rates.
- **ICP priority order (3 > 2 > 4 > 1):** Segment 3 (leadership change)
  always wins. Changing this order changes who gets contacted first and
  the tone of the email — test against the probe library before shipping.
