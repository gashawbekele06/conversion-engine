# Act I — Baseline & Ground Truth

**Repo:** https://github.com/gashawbekele06/conversion-engine
**Interim submission window:** 2026-04-22 21:00 UTC
**Author:** Gashaw Bekele (10 Academy TRP1, Week 10)

## What this document is

This is the Act I deliverable required by the challenge brief: a
≤ 400-word note on the τ²-Bench retail reproduction, the 95% CI on the
dev-slice baseline, cost-per-run, and any unexpected behaviour.

## Status at interim submission

**Harness wired, real scoring run NOT yet executed.** The harness in
`eval/tau2_harness.py` is complete — it partitions tasks into the
30-task dev slice (`eval/dev_slice.json`) and the 20-task sealed
held-out slice (`eval/held_out_slice.json`), runs 5-trial pass@1,
writes trace rows in Langfuse-compatible JSONL form, and aggregates
mean + 95% CI into `eval/score_log.json`.

The interim score log contains **placeholder entries** marked
`run_label: INTERIM_PLACEHOLDER` with `pass_rate_mean: null`. This is
deliberate — per the challenge's evidence-graph integrity rule
("fabricated Tenacious numbers are a disqualifying violation"),
we refuse to report invented benchmark numbers. The real scored run
is scheduled for Day 2 (2026-04-21) once the OpenRouter key and the
pinned program-staff model/temperature are confirmed.

To execute the real run:

```bash
export OPENROUTER_API_KEY=...
pip install -r requirements.txt
git submodule add https://github.com/sierra-research/tau2-bench
pip install ./tau2-bench
python eval/run_baseline.py --slice dev --trials 5 --real
```

## Expected reproduction target

Per the challenge baseline table (published τ²-Bench retail pass@1 with
GPT-5-class models):

| Reference | Expected |
|---|---|
| Published τ²-Bench retail ceiling | ~0.42 pass@1 (Feb 2026 leaderboard) |
| Our dev-tier model (Qwen3-Next / DeepSeek V3.2) soft target | reference ± 3 percentage points |

## Cost envelope (dev tier, Days 1–4)

Targeted < $4 across all probe, ablation, and baseline iterations.
`score_log.json` accumulates `cost_usd_total` per run so drift is visible.

## Unexpected behaviour (to be filled after real run)

- [ ] dev-tier model latency variance
- [ ] tool-use refusal rate vs. published runs
- [ ] dual-control coordination failures (τ²-Bench's central mode)

## Reproducibility checklist

- [x] 30/20 dev/held-out partition file checked into repo
- [x] 5-trial pass@1 runner with mean + 95% CI
- [x] Per-trace cost & p50/p95 latency captured
- [x] Langfuse-compatible JSONL trace sink
- [ ] Real scoring run (blocked on pinned-model confirmation)
- [ ] Published-reference comparison in the final memo

*(≈ 330 words)*
