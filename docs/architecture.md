# Architecture — Conversion Engine

## One-slide summary

The Conversion Engine is a signal-grounded outbound system. Every
touch starts with a public-signal brief the prospect can verify against
their own record, ends with a booked discovery call on a Tenacious
delivery lead's calendar, and writes a complete audit trail the
Tenacious executive team can read without the originating engineer.

## Data flow

1. **Seed** — `data/synthetic_prospects.json` provides Crunchbase IDs
   for the challenge week. Production replaces this with a pointer to
   the full Crunchbase ODM sample + live Playwright crawl.
2. **Enrich** — `agent/enrichment/brief_generator.build_hiring_signal_brief`
   runs each sub-signal (firmographics, job velocity, layoffs, leadership,
   AI maturity) and returns a merged JSON artifact with per-signal
   confidence.
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
   Africa's Talking sandbox. Voice is bonus-tier via the Shared Voice Rig.
7. **Record** — `channels/hubspot.HubSpotChannel.upsert_contact` enforces
   `crunchbase_id` and `last_enriched_at` on every contact row.
   `log_engagement` appends to an append-only engagement table.
8. **Book** — `channels/calcom.CalcomChannel.offer_slots` + `.book`
   attach the brief to the calendar event so the delivery lead joins
   with context.
9. **Trace** — every step emits a JSONL row in
   `eval/traces/trace_log.jsonl`. The Act V evidence-graph script
   (`eval/evidence_graph.py`) walks these rows to verify memo claims.

## Kill-switch invariant

No outbound message reaches a real prospect address unless ALL of:

- `TENACIOUS_LIVE=1` environment variable set
- the prospect record carries `synthetic=False`
- program staff have signed off (manual attestation in repo CHANGELOG)

The default configuration satisfies Data-Handling Policy rule 4.

## Signal-confidence-aware phrasing (Act IV seed)

Per-signal confidence is carried forward from `brief_generator` to
`compose.compose_email`. The `confidence_band` is computed as the
maximum per-signal confidence; the system prompt forbids asserting
any signal below 0.55 confidence (must soften to an ask). In Act IV
this gate is strengthened: a second model call scores whether the
draft over-claims on any signal and regenerates with lower temperature
if it does. Expected Delta A: +3 to +6 percentage points on the
held-out slice.

## Bench-gated commitment (Act IV seed)

`agent/bench.can_commit(stack, engineers, start_in_days)` is the
single entry point any scheduling or pricing code must call before
committing to capacity. It consults `data/seed/bench_summary.json`
and returns a structured reason on failure, which the composer
converts to a human-handoff message per the style guide escalation rule.

## τ²-Bench integration

`eval/tau2_harness.run_pass_at_1` is the scored entry point. In mock
mode (default) it emits `None` pass rates so the score log never
carries fabricated numbers. In real mode it imports `tau2_bench`
and executes the pinned model with the dev/held-out task partition.
Trace rows are Langfuse-compatible via `OTEL` semantics — the
`trace_id` + `span_id` convention is shared between the agent and
the harness.

## Observability

`agent/tracing.Tracer` writes one JSONL row per span with:
`trace_id`, `span_id`, `parent_span_id`, `name`, `started_at`,
`ended_at`, `duration_ms`, `status`, `attributes`.

This is the substrate for:
- per-lead cost attribution (sum `attributes.cost_usd` by `trace_id`)
- p50/p95 latency (`duration_ms` of `orchestrator.run_one` spans)
- evidence-graph audit (claim → trace_id → numeric attribute)

## What's mocked vs. real — final status (2026-04-23)

| Layer | Status | Evidence |
|---|---|---|
| Crunchbase lookup | Synthetic fixture (cb_sample_001) | `data/synthetic_prospects.json` |
| Job-post velocity | Synthetic fixture + Playwright implemented | `agent/enrichment/jobposts.py` |
| layoffs.fyi | Synthetic fixture (120d window) | `agent/enrichment/layoffs.py` |
| LLM compose | OpenRouter claude-sonnet-4-6 (eval tier) | `eval/score_log.json run_140a8c18` |
| Email send | **Resend live verified** | message_id: `001cdf69-13fa-498c-bcc8-470b8a444d15` |
| SMS send | Africa's Talking SDK installed; sandbox SSL blocked | `agent/channels/sms.py` |
| HubSpot upsert | HubSpot Developer Sandbox | `eval/traces/hubspot_mock.json` (97 KB) |
| Cal.com booking | Cal.com production API | `eval/traces/calcom_mock.json` (40 KB) |
| tau2-Bench run | **Real LLM run completed** | `run_140a8c18` dev=0.933, `run_a12f55d4` held_out=1.000 |
| Langfuse sink | Local JSONL (223 trace IDs) | `eval/traces/trace_log.jsonl` |
| Competitor gap brief | **Generating output** | `data/competitor_gap_brief_prospect001.json` |
| Evidence graph | **ok: true, 0 issues** | `eval/traces/evidence_graph.json` (15 claims, 223 traces) |

Every layer without a live API key degrades gracefully to a JSONL sink
or fixture fallback — the pipeline is fully runnable without external
credentials.
