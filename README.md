# Conversion Engine — Tenacious Consulting & Outsourcing

_Automated B2B lead-generation and conversion system. Week 10 challenge,
10 Academy TRP1, April 2026._

> **Interim submission (Wednesday 2026-04-22 21:00 UTC)** covers
> Acts I (τ²-Bench baseline) and II (production stack). See
> [`baseline.md`](baseline.md) and [`docs/interim_report.pdf`](docs/interim_report.pdf).

## Team

| Name | Role | GitHub |
|---|---|---|
| Gashaw Bekele | FDE / solo trainee | [@gashawbekele06](https://github.com/gashawbekele06) |

## What this system does

The Conversion Engine finds prospective B2B clients from public data,
qualifies them against a real hiring-signal brief, composes outbound
grounded in verifiable public facts, runs a nurture loop across
email (primary) and SMS (secondary), and books discovery calls on
Cal.com with a Tenacious delivery lead.

Four ICP segments are served (see `data/seed/icp_definition.md`):

1. Recently-funded Series A/B startups
2. Mid-market platforms restructuring cost
3. Engineering-leadership transitions
4. Specialized capability gaps (gated on AI-maturity ≥ 2)

Every outbound message traces to a public signal; every lead object
in HubSpot references a Crunchbase record ID and an
`last_enriched_at` timestamp.

## Architecture

```
 ┌──────────────────────┐     ┌──────────────────────┐
 │ Crunchbase ODM sample│     │ layoffs.fyi CSV      │
 └──────────┬───────────┘     └──────────┬───────────┘
            │                            │
 ┌──────────▼────────────────────────────▼───────────┐
 │  Enrichment pipeline  (agent/enrichment/*)         │
 │  • firmographics       • layoffs     • leadership  │
 │  • job-post velocity   • AI maturity • peer gap    │
 │  → hiring_signal_brief.json + competitor_gap.json  │
 └──────────┬─────────────────────────────────────────┘
            │
 ┌──────────▼─────────────────────────────────────────┐
 │  Agent core  (agent/orchestrator.py)               │
 │   1. ICP segment classify (w/ confidence)          │
 │   2. Compose outbound (signal-confidence-aware)    │
 │   3. Kill-switch gate → staff sink unless LIVE     │
 │   4. Email (Resend/MailerSend) / SMS (AT sandbox)  │
 │   5. HubSpot MCP upsert + engagement log           │
 │   6. Cal.com booking with context brief attached   │
 └──────────┬─────────────────────────────────────────┘
            │
 ┌──────────▼─────────────────────────────────────────┐
 │  Tracing / Eval                                    │
 │   • agent/tracing.py (JSONL + Langfuse)            │
 │   • eval/tau2_harness.py (pass@1, 95% CI)          │
 │   • eval/evidence_graph.py (Act V audit)           │
 └────────────────────────────────────────────────────┘
```

## Setup

```bash
# 1. Clone
git clone https://github.com/gashawbekele06/conversion-engine.git
cd conversion-engine

# 2. Environment
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Config
cp .env.example .env
# Edit .env — leave TENACIOUS_LIVE UNSET for the challenge week.

# 4. Smoke-test (mock providers, no API keys required)
python -m agent.main enrich cb_sample_001
python -m agent.main run-one prospect_001
python -m agent.main run-all

# 5. τ²-Bench baseline (mock; replace with --real on Day 2)
python eval/run_baseline.py --slice dev --trials 5

# 6. Webhooks (only needed for Act II real-channel mode)
uvicorn agent.webhooks:build_app --factory --reload --port 8080
```

## Directory layout

```
conversion-engine/
├── README.md                     ← you are here
├── baseline.md                   ← Act I deliverable
├── requirements.txt
├── .env.example
├── agent/
│   ├── __init__.py
│   ├── config.py                 ← env → Config dataclass
│   ├── kill_switch.py            ← hard-gates all outbound
│   ├── tracing.py                ← JSONL trace sink
│   ├── llm.py                    ← OpenRouter + deterministic fallback
│   ├── compose.py                ← signal-confidence-aware composer
│   ├── bench.py                  ← bench-gated commitment helpers
│   ├── orchestrator.py           ← end-to-end thread runner
│   ├── webhooks.py               ← FastAPI reply ingesters
│   ├── main.py                   ← CLI
│   ├── channels/
│   │   ├── email.py              ← Resend / MailerSend / mock
│   │   ├── sms.py                ← Africa's Talking / mock; STOP/HELP
│   │   ├── hubspot.py            ← MCP-style tools; mock-backed
│   │   └── calcom.py             ← Cal.com booking; mock-backed
│   └── enrichment/
│       ├── crunchbase.py
│       ├── layoffs.py
│       ├── jobposts.py           ← Playwright in real mode
│       ├── leadership.py
│       ├── ai_maturity.py        ← 0–3 score + confidence
│       ├── competitor_gap.py     ← 5–10 peer top-quartile gap
│       └── brief_generator.py    ← merge all signals → brief.json
├── data/
│   ├── seed/
│   │   ├── icp_definition.md
│   │   ├── style_guide.md
│   │   ├── bench_summary.json
│   │   ├── pricing.json
│   │   ├── case_studies.md
│   │   └── email_sequences.md
│   └── synthetic_prospects.json  ← 5 seeded synthetic prospects
├── eval/
│   ├── tau2_harness.py
│   ├── run_baseline.py
│   ├── evidence_graph.py
│   ├── score_log.json            ← placeholder until Day 2
│   ├── dev_slice.json            ← 30-task dev partition
│   ├── held_out_slice.json       ← 20-task sealed partition
│   └── traces/
│       ├── trace_log.jsonl       ← every tool call, every LLM call
│       ├── email_sink.jsonl
│       ├── sms_sink.jsonl
│       ├── hubspot_mock.json
│       └── calcom_mock.json
├── probes/                       ← populated in Act III (Day 3)
├── docs/
│   ├── architecture.md
│   └── interim_report.pdf        ← interim deliverable
└── tests/
    └── test_smoke.py
```

## Data-handling policy compliance

| Rule | How this repo satisfies it |
|---|---|
| 1 — No real Tenacious customer data leaves Tenacious | Only synthetic fixtures in `data/synthetic_prospects.json`. |
| 2 — All prospect traffic is synthetic | Orchestrator sets `synthetic=True` for every seeded prospect; kill switch enforces. |
| 3 — Seed materials not redistributed | ICP / style guide / pricing are Tenacious-internal representations; public repo carries only the necessary schema. |
| 4 — Kill switch exists and defaults unset | `TENACIOUS_LIVE` env var; default False routes all to `STAFF_SINK_EMAIL`. |
| 5 — Outputs tagged `draft` | Every email/SMS mock payload carries `metadata.draft=true` (see `channels/email.py`). |

## Budget envelope

Target ≤ $20/trainee for the week. The tracer records `usd_cost` per
LLM call; `score_log.json` aggregates per-run cost so overruns are
visible before they happen.

## What's next (Days 3–7)

- Day 3 — Act III adversarial probes (30+ structured entries)
- Day 4 — Act IV mechanism (signal-confidence-aware phrasing +
  bench-gated commitment)
- Day 5 — held-out scoring run, Delta A / B / C
- Day 6 — Act V two-page memo + evidence_graph.json
- Day 6 stretch — market-space map (distinguished tier)

## Inheritance note for the next engineer

If you inherit this system, read these in order:

1. `baseline.md` — what's real vs. placeholder at submission time
2. `data/seed/icp_definition.md` — grading-fixed segment names
3. `agent/kill_switch.py` — the only outbound gate
4. `agent/enrichment/brief_generator.py` — the signal → brief contract
5. `eval/tau2_harness.py` — harness wiring
