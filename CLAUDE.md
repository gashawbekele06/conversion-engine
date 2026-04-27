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

5. **Peer-count gate at 3.** When `competitor_gap["peer_count"] < 3`, suppress all gap trend claims. Implemented in `agent/compose.py` via `_compose_gap_section()`. Constants `PEER_COUNT_SUPPRESS=3`, `PEER_COUNT_HEDGE=5`. See `method.md` for design and `ablation_results.json` for Delta A (P-028 trigger rate 0.40 → 0.0, p=0.015).

6. **Cal.com booking requires a real prospect reply — never auto-book.** `run_one()` defaults to `simulate_reply=False`. Booking is ONLY triggered inside `_on_email_reply()` (or `_on_sms_reply()`) when a real inbound reply arrives at `POST /webhooks/email`. The `simulate_reply=True` flag exists exclusively for the eval harness and the `--simulate` CLI flag. **Never** set it True in production code paths. See `agent/orchestrator.py`.

---

## Reply Routing Setup (Required for Real Email Demo)

The outbound email is sent from `onboarding@resend.dev`. When the prospect (e.g. `gashawbekelek@gmail.com`) clicks **Reply**, their email client sends the reply to the address in the `Reply-To` header. Without this header set to a monitored inbox, the reply goes to Resend's no-reply sender and `POST /webhooks/email` is never called.

**Steps to enable real reply handling:**

1. **Add your domain in Resend** → Dashboard → Domains → Add Domain.
2. **Enable Inbound Routing** for that domain → set the inbound URL to:
   ```
   https://<your-server-host>/webhooks/email
   ```
3. **Set `TENACIOUS_REPLY_TO`** in `.env` to an address on that domain:
   ```
   TENACIOUS_REPLY_TO=replies@yourdomain.com
   ```
4. *(Optional)* Set `RESEND_WEBHOOK_SECRET` for HMAC signature verification on inbound events.

**Without a custom domain (local testing):**
```bash
# 1. Send the email (no booking)
python -m agent.main run-one prospect_002

# 2. Simulate the reply firing through the webhook handler
python -m agent.main simulate-reply prospect_002

# 3. Observe Cal.com booking in HubSpot mock
```

**Sink-routing note:** When `TENACIOUS_LIVE` is unset (default), outbound emails are routed to the staff sink (e.g. `gashawbekelek@gmail.com`). The reply comes back FROM that address, not from the synthetic prospect address. `Orchestrator._reply_lookup` handles this mapping automatically — the reply handler resolves `gashawbekelek@gmail.com → marcus@glenmark.example` before any HubSpot or Cal.com operation.

---

## Known Limitations (Successor Will Hit These)

### 1. P-028 Gap Over-Claiming — FIXED
Peer-count gate implemented in `agent/compose.py` via `_compose_gap_section()`. Constants `PEER_COUNT_SUPPRESS=3`, `PEER_COUNT_HEDGE=5`. Structural check: impossible to assert a trend claim when `peer_count < 3`. Delta A: P-028 trigger rate 0.40 → 0.0, Fisher exact p=0.015. See `ablation_results.json`.

### 2. tau2-Bench Not Installed (Python 3.14.4 incompatibility)
`eval/tau2_harness.py` falls back to `llm_backed_v1` because `tau2_bench` requires Python `<3.14` and this environment runs 3.14.4. All `pass@1` scores reflect keyword-grounded LLM response checks, not dual-control Sierra Research benchmark. Full dual-control scoring available once Python version is compatible. **Priority: MEDIUM. Unblocked by Python version upgrade.**

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
