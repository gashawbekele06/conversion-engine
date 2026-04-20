# Tenacious Outbound Voice — Style Guide

> Tone markers MUST be preserved in any agent-generated email/SMS.
> Act III probes test for tone drift; Act IV may add a tone-preservation
> mechanism. This file is the source of truth.

## Tone markers (MUST preserve)

1. **Grounded in public fact.** Every claim traces to a verifiable
   public signal. If the agent cannot cite, it asks rather than asserts.
2. **Brief.** Cold email ≤ 120 words. SMS ≤ 280 chars. Discovery-call
   confirmation ≤ 80 words.
3. **No vendor-speak.** Banned phrases: "unlock value", "leverage",
   "solutions provider", "synergize", "best-in-class", "world-class",
   "at scale" (unless quantified), "game-changer", "circle back",
   "touch base".
4. **Specific over generic.** Name the company, name the signal,
   name the number. Not "we noticed you're growing" — instead
   "your open Python-engineering roles went from 3 to 11 between
   Feb 18 and Apr 15".
5. **Respectful of reader time.** One ask per message. No multi-paragraph
   pitches in the first touch.
6. **Soft on recommendations.** Use "may be worth" not "you need to".
   Use "teams in this state typically" not "you must".

## Tone markers (MUST avoid)

- Condescension about a CTO's awareness of their own company.
- Implying urgency that is not grounded in signal ("act now", "limited time").
- Offshore-coded language that triggers in-house hiring defensiveness
  ("we can do it cheaper", "replace your team"). Use "augment" or
  "add capacity alongside".
- Compliance-style language when talking to a founder.
- Emoji in first three touches. Emoji acceptable after prospect uses one.

## Opening patterns (good)

```
Subject: Python hiring velocity after your Series B

Hi {first_name},

You closed a $14M Series B in February and your public Python-engineering
roles went from 3 to 11 between then and now. The typical bottleneck
for teams in that state is recruiting capacity rather than budget.

Three companies at your stage & stack have filled similar gaps with
a dedicated offshore squad. Happy to share how it went if useful —
30 minutes next week?

— {sender_name}, Tenacious
```

## Opening patterns (bad — do NOT generate)

```
Subject: Unlock the power of outsourcing!  ← vendor-speak, hype

Hi there,  ← no name

We noticed you're growing  ← vague, not grounded

We are a world-class offshore engineering partner that  ← self-pitch before value

leverages synergies to help you scale faster.  ← banned words

Interested?  ← aggressive single-ask, no out
```

## Re-engagement sequence (after 5-day silence)

- Touch 2: reference a NEW public signal since touch 1 (new hire,
  new blog post, new funding), not a repeat of the same brief.
- Touch 3: offer a specific research artifact (competitor-gap one-pager)
  in exchange for a 15-minute call. No more cold asks after this.
- After touch 3: move to quarterly re-engagement only.

## Scheduling language (Cal.com handoff)

When the prospect accepts, the agent MUST:
1. Confirm timezone explicitly (EU, US, EAT).
2. Attach the hiring_signal_brief.json and competitor_gap_brief.json
   as a context brief for the delivery lead.
3. NEVER promise specific bench capacity the bench_summary.json
   does not show. Route to a human if asked about specific staffing.

## Signal-confidence-aware phrasing

| Evidence weight | Example phrasing |
|---|---|
| High (multiple high-weight inputs) | "Your public Python-engineering roles tripled since your Series B" |
| Medium (one high-weight + one medium) | "It looks like your Python hiring has picked up since your Series B" |
| Low (single medium-weight signal) | "We noticed some engineering-role activity since your Series B — wondering if recruiting capacity is tight?" |

This mapping is ground truth for the Act IV tone-preservation / confidence-aware
mechanism.
