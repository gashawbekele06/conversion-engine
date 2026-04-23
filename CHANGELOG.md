# Changelog — Conversion Engine

## [Final] 2026-04-23

### Completed

**Act I — Baseline**
- Real LLM baseline run completed: `run_140a8c18` (claude-sonnet-4-6 via OpenRouter)
  - Dev slice (30 tasks, 1 trial): mean pass@1 = 0.933, cost = $0.041, p50 = 4,166 ms, p95 = 6,995 ms
- Held-out validation run: `run_a12f55d4` (20 tasks): mean pass@1 = 1.000, cost = $0.023
- Simulation baseline (reference): `run_14e99ac7` Bernoulli(p=0.40), pass@1 = 0.453
- `baseline.md` updated with real run results and reproducibility checklist

**Act II — Production Stack**
- Email (Resend): live delivery verified — message_id: `001cdf69-13fa-498c-bcc8-470b8a444d15`
  - Delivered to staff sink (gashawbekelek@gmail.com); kill-switch confirmed
- SMS (Africa's Talking): SDK installed (africastalking-2.0.2); AT sandbox infrastructure broken
  - Root cause: `api.sandbox.africastalking.com:443` serves plain HTTP (no TLS); all plain HTTP
    requests on ports 80 and 443 return bare `400 Bad Request` before reading request headers —
    confirmed via raw TCP, curl (Windows SChannel), and Python ssl module; not network/WARP related
  - Code path is correct: warm-lead gate (`WarmLeadRequired`), kill-switch routing, and mock-sink
    fallback all verified; 7/7 smoke tests pass
  - Warm-lead gate enforced in code (`WarmLeadRequired` exception)
- HubSpot Developer Sandbox: upsert + engagement log confirmed in `eval/traces/hubspot_mock.json`
- Cal.com: slot offer + booking flow confirmed in `eval/traces/calcom_mock.json`
- Langfuse: local JSONL sink active (223 trace IDs in `eval/traces/trace_log.jsonl`)
- Orchestrator end-to-end: `python -m agent.main run-one prospect_001` — all 9 steps complete

**Enrichment Pipeline**
- Competitor gap brief generating output: `data/competitor_gap_brief_prospect001.json`
  - Sector: fintech | Target score: 1/3 | Top-quartile threshold: 3 | 3 gap practices identified

**Act V — Evidence Graph**
- Validator output: `{"ok": true, "issues": [], "n_claims": 15, "n_traces": 223}`
- Graph file: `eval/traces/evidence_graph.json`

**Tests**
- All 7 smoke tests pass: `pytest tests/ -v` — 7 passed in 0.35s
- Python 3.14.4, pytest 9.0.3

**Dependencies added**
- `resend==2.29.0` — email delivery
- `africastalking==2.0.2` — SMS (sandbox)

**Files changed**
- `baseline.md` — updated with real run IDs, numbers, and observations
- `docs/architecture.md` — final status table (mocked vs. real) updated
- `data/competitor_gap_brief_prospect001.json` — new artifact
- `interimreport.md` + `interimreport.pdf` — interim report deliverables
- `generate_pdf.py` — PDF generation script

---

## [Interim] 2026-04-22

- Acts I–V scaffolded
- Simulation baseline: `run_14e99ac7`, pass@1 = 0.453, 95% CI [0.424, 0.483]
- All 5 production stack components wired with graceful mock fallback
- Kill-switch default-closed (TENACIOUS_LIVE unset → staff sink)
- 5 enrichment signals with per-signal confidence
- Evidence graph scaffold: 15 claims defined
