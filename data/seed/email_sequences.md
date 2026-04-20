# Sample Outbound Email Sequences (Tenacious Voice)

> The agent may rewrite these but must preserve the tone markers in
> `style_guide.md`. Every sequence is keyed by ICP segment.

## Sequence A — Cold (Segment 1: recently funded)

### A.1 — Cold open (signal-grounded)

```
Subject: Python hiring velocity after your {round}

Hi {first_name},

{company} closed a ${round_amount} {round} in {round_month} — and your
public Python roles went from {roles_before} to {roles_after} since then.
The typical bottleneck at this stage is recruiting capacity, not budget.

Three companies at similar stage/stack have filled this gap with a
dedicated squad. 30 minutes next week to share how it went?

— {sender_name}, Tenacious
```

### A.2 — Follow-up (3 business days, no reply)

```
Subject: re: Python hiring velocity after your {round}

Hi {first_name},

Since my last note, {new_signal_sentence}. If recruiting capacity is
the constraint, happy to send a short competitor-gap one-pager on how
{sector} Series B teams are closing similar gaps — no call needed.

— {sender_name}
```

### A.3 — Breakup (5 business days, no reply)

```
Subject: closing out

Hi {first_name},

No reply on my last two — I'll stop here. If the timing isn't right,
that's fine. If helpful in a quarter, reach out to {sender_email}.

— {sender_name}
```

---

## Sequence B — Cold (Segment 2: restructuring)

### B.1

```
Subject: preserving delivery capacity post-{restructure_event}

Hi {first_name},

Tenacious has helped two mid-market {sector} teams preserve delivery
throughput through restructures — net output within 95% CI of pre-RIF
baseline by week 9. Not a cost-cutting pitch: a capacity-preservation
pitch.

Worth 30 minutes?

— {sender_name}, Tenacious
```

---

## Sequence C — Cold (Segment 3: leadership transition)

### C.1

```
Subject: welcome to {company} — quick resource

Hi {first_name},

Congrats on the {role} role at {company}. Most new {role}s reassess
offshore/vendor mix in the first 6 months. If that's on your list,
we have a short note on how three peer companies have approached it —
attaching nothing, happy to send if useful.

— {sender_name}, Tenacious
```

---

## Sequence D — Cold (Segment 4: capability gap)

### D.1 (only if AI maturity >= 2)

```
Subject: {specific_build_signal} — quick note

Hi {first_name},

Saw your {conference_talk | blog_post | rfp} on {specific_build}. We
recently shipped a similar {agentic_system | ml_platform | data_contracts}
project for a {peer_sector_size}. Delivered in {n_months} months with a
{n}-engineer team.

30 minutes to compare notes on architecture choices?

— {sender_name}, Tenacious
```

---

## Sequence E — Warm re-engagement (prospect replied once, then silent)

### E.1

```
Subject: quick follow-up on our note

Hi {first_name},

Following up on your reply about {topic}. If a 15-minute call works
better than email for the scheduling back-and-forth, happy to switch to
SMS — just reply "sms" and I'll text you slot options.

— {sender_name}
```

---

## Agent rewrite rules

- `{new_signal_sentence}` MUST be a genuinely new public signal, not a
  repeat of the cold open's signal.
- `{specific_build}` MUST reference evidence in the enrichment brief;
  if no such evidence, fall back to Sequence A.
- If the AI-maturity score is 0 or 1 and the segment is 4, the agent
  MUST abstain and pick Sequence A or B instead.
- If bench_summary shows 0 available engineers for the relevant stack,
  the agent MUST NOT use Sequence A/B/D. Use Sequence C (leadership)
  or route to manual queue.
