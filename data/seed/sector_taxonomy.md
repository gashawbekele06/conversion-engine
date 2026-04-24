# Sector Taxonomy and Competitor Selection Criteria

Used by `agent/enrichment/competitor_gap.py` to identify sector peers for the competitor gap brief.

---

## Sector Values

The `sector` field in `data/synthetic_prospects.json` must be one of the following canonical values. The agent uses exact string matching — do not use synonyms.

| Sector Key | Description | Example Companies |
|------------|-------------|-------------------|
| `fintech` | Financial technology: payments, lending, banking infrastructure, compliance SaaS | Nimbus Ledger, Vantage Pay, ClearStake Finance, Mosaic Banking Tech |
| `ecommerce` | E-commerce platforms, commerce infrastructure, retail tech | Glenmark Commerce, ShopStream, Basket.io |
| `healthtech` | Health technology: patient platforms, clinical SaaS, health data | Aurelia Health, MedRoute AI, CareSync Platform |
| `ml-infra` | Machine learning infrastructure: model serving, MLOps, data platforms | Finch ML Systems, Synapse ML, Lattice Inference |
| `logistics-saas` | Logistics and supply chain SaaS: route optimization, freight, warehouse | Kestrel Logistics, FlowFreight, RouteIQ |
| `devtools` | Developer tools: CI/CD, observability, security tooling | (no current prospects — expand in production) |
| `hrtech` | HR and talent management platforms | (no current prospects — expand in production) |

---

## Competitor Selection Criteria

To qualify as a sector peer for gap brief generation, a company must:

1. **Same sector key** — exact match on the `sector` field. Cross-sector comparisons are not valid for gap briefs.
2. **Not the target** — `crunchbase_id != target_crunchbase_id`.
3. **Scorable by AI maturity** — `score_ai_maturity(crunchbase_id)` must return a non-None `MaturityScore`. Companies with no signal data are excluded from the peer distribution.
4. **Not disqualified by ICP filters** — companies that are current Tenacious clients, or are listed as clients of direct Tenacious competitors (Andela, Turing, Revelo, TopTal) on public case-study pages, are excluded from peer comparisons to prevent competitive intelligence conflicts.

---

## Sparse Sector Handling

When fewer than 5 viable peers remain after filtering:

- `peer_count < 3`: Suppress all gap trend claims in outbound email (see `method.md` peer-count gate). Return brief with `gap_practices=[]` or suppress gap section in compose.py.
- `peer_count 3–4`: Use hedged language ("a small number of companies in your space..."). Do not name specific peers unless their evidence is high-confidence (confidence >= 0.7).
- `peer_count >= 5`: Full assertion tier permitted.

The `_top_quartile_threshold` function in `competitor_gap.py` handles the distribution math for small cohorts: when `len(scores) < 4`, it returns `max(scores)` as the threshold rather than attempting a quartile split on an insufficient sample.

---

## Adding New Sectors

When adding a new sector to `data/synthetic_prospects.json`:

1. Add the sector key to the table above.
2. Add at least 3 peer records to `synthetic_prospects.json` with matching `sector` field and populated `signals.ai_maturity_inputs`.
3. Run `python -m agent.main enrich <crunchbase_id>` on the new prospect and verify `peer_count >= 3` in the competitor gap brief output.
4. If `peer_count < 3`, add more peer fixture records before deploying to production.
