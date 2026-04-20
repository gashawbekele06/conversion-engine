# Tenacious Consulting & Outsourcing — ICP Definition

> Seed input for the Conversion Engine. Segment names are fixed for grading.
> Qualifying/disqualifying filters may be adapted by the agent.

## Segment 1 — Recently-funded Series A/B startups

**Description.** Companies that closed a $5–30M round in the last 6 months.
Typically 15–80 people. Hiring velocity outstripping recruiting capacity.

**Qualifying filters**
- `funding.round` in {`Series A`, `Series B`}
- `funding.amount_usd` between `5_000_000` and `30_000_000`
- `funding.announced_on` within last `180` days
- `employee_count` between `15` and `80`
- `open_engineering_roles >= 3`

**Disqualifying filters**
- Layoff event in last 120 days (route to Segment 2 instead)
- Stealth / no public hiring signal

**Why they buy.** Need to scale engineering output faster than in-house
hiring can support. Budget is fresh and runway is the clock.

---

## Segment 2 — Mid-market platforms restructuring cost

**Description.** Public or late-stage companies (200–2,000 people)
under pressure to cut burn without cutting output. Often post-layoff
or post-restructure.

**Qualifying filters**
- `employee_count` between `200` and `2000`
- ANY of: layoff event in last `120` days, public restructure memo,
  post-IPO down-round, activist investor pressure
- `open_engineering_roles >= 1` (proving not a full hiring freeze)

**Disqualifying filters**
- Series Seed/A with no layoff signal (belongs to Segment 1)
- Company in active bankruptcy proceedings

**Why they buy.** Replace higher-cost roles with offshore equivalents;
keep delivery capacity; quiet signal of operational discipline to the board.

---

## Segment 3 — Engineering-leadership transitions

**Description.** Companies with a new CTO or VP Engineering appointed
in the last 90 days.

**Qualifying filters**
- `leadership.role` in {`CTO`, `VP Engineering`, `Chief Technology Officer`}
- `leadership.appointment_date` within last `90` days
- Company has a named engineering team on LinkedIn/careers page

**Disqualifying filters**
- Interim appointment with explicit "acting" label
- Company too small to have been running a multi-team engineering org

**Why they buy.** New leaders routinely reassess vendor contracts and
offshore mix in their first 6 months. Narrow but high-conversion window.

---

## Segment 4 — Specialized capability gaps

**Description.** Companies attempting a specific build — ML platform
migration, agentic systems, data contracts — where in-house skills
do not match the need.

**Qualifying filters**
- `ai_maturity_score >= 2` (gates this segment — do NOT pitch Segment 4
  at AI maturity 0 or 1)
- Public signal of a specific build: blog post, conference talk, RFP,
  or named initiative
- `open_roles` mentions specific stack: {`MLOps`, `Agentic`, `LLM`,
  `Data Contracts`, `Vector DB`}

**Disqualifying filters**
- AI maturity score < 2
- No public evidence of the capability gap

**Why they buy.** Project-based consulting, not outsourcing. Higher
margin, shorter commitment, portfolio value.

---

## Cross-segment confidence reporting

The agent MUST report a confidence score (0.0–1.0) alongside every
segment assignment. Confidence < 0.6 routes to a generic exploratory
email, not a segment-specific pitch.

| Confidence band | Agent behaviour |
|---|---|
| >= 0.85 | Segment-specific pitch, direct |
| 0.60 – 0.84 | Segment-specific pitch, softened language, ask-rather-than-assert framing |
| < 0.60 | Generic exploratory email; human review flag raised |

## Mutual-exclusion rule

A single prospect may match more than one segment. Priority order when
multiple match (highest to lowest):

1. Segment 3 (leadership transition) — narrowest window
2. Segment 2 (restructuring) — layoff signal dominates funding signal
3. Segment 4 (capability gap) — only if AI maturity >= 2
4. Segment 1 (recently funded) — default if others do not apply
