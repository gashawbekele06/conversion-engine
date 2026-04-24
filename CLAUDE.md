# CLAUDE.md — Inheritor Context for Tenacious Conversion Engine

This file is the first thing a successor engineer or AI assistant should read. It records decisions, constraints, and known failure modes that are not obvious from reading the code alone.

---

## What This Repo Does

Automated B2B outbound pipeline for Tenacious Consulting & Outsourcing. For each synthetic prospect it:
1. Enriches with 6 public signals (funding, job velocity, layoffs, leadership, AI maturity, competitor gap)
2. Classifies into one of 4 ICP segments with strict priority order (3 > 2 > 4 > 1)
3. Composes a signal-grounded cold email via LLM
4. Routes through a kill switch (default: staff sink, never live)
5. Upserts HubSpot CRM and books Cal.com discovery call

All prospects in this repo are **synthetic**. No real company data or real outbound has been sent.

---

## Critical Constraints — Do Not Break These

1. **Kill switch must default closed.** `TENACIOUS_LIVE` unset = all outbound to staff sink. Never set `TENACIOUS_LIVE=1` in production without program-staff review. See `agent/kill_switch.py`.

2. **SMS is warm-lead only.** `SMSChannel.send()` raises `WarmLeadRequired` if no prior inbound reply exists in `eval/traces/sms_sink.jsonl`. Pass `warm_lead=True` only after confirming engagement. This is enforced in code, not just documented.

3. **Bench capacity must be checked before pitching.** `data/seed/bench_summary.json` is the authoritative source. If a stack shows 0 available engineers, the agent must not pitch that capability. See `bench_summary.json` honesty_constraint field.

4. **Confidence gate at 0.55.** When `confidence_per_signal` for a hiring signal is below 0.55, the agent must use hedged language ("per public records, it appears...") not assertive language. See `agent/compose.py`.

5. **Peer-count gate at 3.** When `competitor_gap["peer_count"] < 3`, suppress all gap trend claims. This is the P-028 target failure mode — currently NOT YET IMPLEMENTED in compose.py. See `method.md` for the fix.

---

## Known Limitations (Successor Will Hit These)

### 1. P-028 Gap Over-Claiming — NOT Fixed
The peer-count gate described in `method.md` is designed but not implemented. `compose.py` currently does not check `peer_count` before generating gap language. Thin-sector prospects (logistics-saas, ml-infra with < 3 peers) will receive over-claimed gap emails. **Priority: HIGH. Fix cost: 0.5 days.**

### 2. tau2-Bench Not Installed
`eval/tau2_harness.py` falls back to a keyword-grounded response check because the `tau2` package is not installed. All `pass@1` scores in `eval/score_log.json` reflect keyword matching, not the dual-control Sierra Research benchmark. Install via the submodule or `pip install tau2-bench` when available. **Priority: MEDIUM.**

### 3. Africa's Talking Sandbox TLS Broken
`api.sandbox.africastalking.com:443` serves plain HTTP during TLS handshake as of 2026-04-23. Port 80 returns `400 Bad Request` before reading headers. The live API (`AT_USERNAME != "sandbox"`) works when a valid live key is provided but requires account activation for outbound SMS. Mock sink output in `eval/traces/sms_sink.jsonl` is the current evidence of SMS channel correctness. **Priority: LOW (third-party outage).**

### 4. delta_60d = 0 for Live Playwright Scrapes
`agent/enrichment/jobposts.py` sets `delta_60d=0` on live Playwright scrapes because computing velocity requires a historical snapshot. The fixture path returns real `delta_60d` values. In production, a nightly snapshot job would be needed to compute true 60-day velocity. **Priority: MEDIUM.**

### 5. HubSpot SMS Reply Updates — Implemented
`Orchestrator._register_sms_reply_handler()` registers a HubSpot callback at init time. Inbound SMS replies (reply/stop/help) update the CRM stage and log an engagement. Phone→email mapping is populated per prospect in `run_one` via `_sms_phone_email`. Unknown numbers (not in the map) are silently ignored.

### 6. GitHub Org Disambiguation Not Implemented
`agent/enrichment/ai_maturity.py` uses a `github_org_activity` field from the fixture. In production, the scraper could attribute activity from a same-prefix but unrelated GitHub org (P-027). A disambiguation step comparing org description to company name is needed before scoring. **Priority: LOW.**

---

## Directory Index

```
conversion-engine/
  agent/                  Core pipeline code
    channels/             Email (Resend), SMS (AT), HubSpot, Cal.com adapters
    enrichment/           6 signal modules + brief builder + AI maturity scorer
    config.py             All config fields with env var defaults
    orchestrator.py       9-step end-to-end pipeline per prospect
    compose.py            LLM email composer with signal-confidence gating
    kill_switch.py        Route resolver: live vs. staff sink
    llm.py                LLM client: OpenRouter (dev) + Anthropic SDK (eval)
    webhooks.py           FastAPI inbound webhook handlers
  data/
    seed/                 ICP definition, bench summary, pricing, case studies
    synthetic_prospects.json   5 target prospects + 11 sector peers
  eval/
    traces/               trace_log.jsonl (5191 rows), email/sms sinks, evidence graph
    score_log.json        All benchmark run results
    latency_summary.json  p50/p95 latency from real orchestrator spans
  probes/
    probe_library.json    31 adversarial probes across 10 categories
  docs/
    architecture.md       Data flow diagram + setup instructions
  tests/                  7 smoke tests (all passing)
  method.md               Mechanism design: peer-count gate, 3 ablations, test plan
  target_failure_mode.md  P-028 selected, business cost arithmetic, 2 alternatives
  memo.md                 Act V decision memo (source)
  memo.pdf                2-page decision memo PDF
  baseline.md             Act I benchmark baseline with reproducibility checklist
  CHANGELOG.md            Chronological record of all acts
  .env                    Secrets (gitignored — see .env.example for template)
```

---

## Recommended First Reads (In Order)

1. `data/seed/icp_definition.md` — understand who gets contacted and why
2. `agent/kill_switch.py` — understand what prevents live outbound
3. `agent/orchestrator.py` — understand the 9-step pipeline
4. `target_failure_mode.md` + `method.md` — understand the unresolved failure and the fix design
5. `probes/probe_library.json` — understand all 31 known failure modes before changing compose.py

---

## Run Order for Local Bootstrap

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Fill in: OPENROUTER_API_KEY, RESEND_API_KEY, HUBSPOT_TOKEN, CALCOM_API_KEY

# 3. Verify setup
pytest tests/ -v              # expect: 7 passed

# 4. Dry run (no LLM cost, no external calls)
python -m agent.main dry-run

# 5. Single prospect end-to-end
python -m agent.main run-one prospect_001

# 6. Benchmark (dev tier, ~$0.002 total)
python eval/run_bench.py

# 7. Validate evidence graph
python eval/evidence_graph.py eval/traces/evidence_graph.json
```
