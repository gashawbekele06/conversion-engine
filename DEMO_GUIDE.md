# Step-by-Step Demo Guide
## Rubric Coverage: All 5 Items · Dashboard + HubSpot + Africa's Talking + Cal.com

---

## WHAT THE RUBRIC REQUIRES — QUICK MAP

| Rubric Item | Max | What Must Appear On Screen |
|---|---|---|
| End-to-End Conversion Flow | 5 | Same prospect: email → reply → qualified → booking (continuous, traceable) |
| Signal Brief Artifact Visibility | 5 | Both briefs, per-signal confidence bars, AI maturity score /3 |
| HubSpot CRM Artifact State | 5 | Populated record + session-current timestamp (not stale) |
| Cal.com Booking Artifact State | 5 | Confirmed booking: date, time, attendee name, event type |
| Demo Production Compliance | 5 | Under 8 minutes, no login to view, grader can follow every section |

**Best prospect to use:** Aurelia Health (Priority 1 sidebar) — Daniela Ruiz, CTO.
Segment 3 Leadership Transition produces the richest signal brief and the clearest lifecycle.

---

## BEFORE YOU START — SET UP 4 BROWSER TABS

Open these tabs now and leave them ready:

| Tab # | URL | Purpose |
|---|---|---|
| Tab 1 | `http://localhost:5173` | Dashboard — main demo screen |
| Tab 2 | `https://app-eu1.hubspot.com/contacts/` | HubSpot live portal |
| Tab 3 | `https://account.africastalking.com/apps/gashaw/sms` | AT sent messages log |
| Tab 4 | Gmail or `https://mail.google.com` | Resend email proof |

Start recording on Tab 1 with no prospect selected.

---

## STEP 1 — Prove the System is Live (30 seconds)

**On: Dashboard Tab 1**

1. Point to the 4 header tiles: **72.7% · 150 · $0.0199 · 106s**
2. Say these are real τ²-Bench evaluation results, not placeholders.
3. Point to the sidebar — 5 prospects grouped by Priority 1–4.
4. Say Priority 1 = Leadership Transition (highest buying urgency).

**Rubric covered:** Demo Production Compliance (grader can see what the system is and why)

---

## STEP 2 — Select the Prospect and Run the Pipeline (2 minutes)

**On: Dashboard Tab 1**

1. Click **Aurelia Health** in the sidebar under Priority 1.
2. The Prospect Card appears: *Daniela Ruiz, CTO, 340 employees, Segment 3.*
3. Point to the Journey Banner — shows **Prospect Selected → Brief Generated**.
   Say: "Six stages — watch them all advance."
4. Click **▶ Run Pipeline for Daniela**.
5. Narrate each step as it animates (keep talking for ~90 seconds):
   - Step 1–2: Enrichment (6 public signals)
   - Step 3: Segment classification
   - Step 4: Email composition via Claude
   - Step 5: Kill-switch check
   - Step 6: **Live Resend API send** ← say "real API call"
   - Step 7: **HubSpot upsert** ← say "real API call"
   - Step 8: HubSpot engagement log
   - Step 9: **Cal.com booking** ← say "real API call"
6. When ✓ Complete appears — point to it.
   Say: "Cal.com booking ID and HubSpot contact ID — real identifiers from real APIs."
7. Point to Journey Banner — now shows **Discovery Call Booked**.

**Rubric covered:** End-to-End Conversion Flow (pipeline executed, email sent, booking confirmed)

---

## STEP 3 — Show the Signal Brief (45 seconds)

**On: Dashboard Tab 1 → Signal & Gap Briefs tab**

1. Click **Signal & Gap Briefs** tab.
2. Point to the **segment badge**: Segment 3 — Leadership Transition.
3. Point to the **reason field**: "leadership change detected within 90 days."
4. Point to the **5 confidence bars** (Funding, Job Velocity, Layoffs, Leadership, AI Maturity).
   Say: "Green = high confidence → assertive language. Below 55% → hedged language. Gate enforced in code."
5. Point to the **AI Maturity Score card** on the right.
   Say: "Score X out of 3. This determines the pitch angle."
   *(The /3 denominator must be visible — this is a rubric requirement.)*
6. Scroll down to **Competitor Gap Brief**.
7. Point to the **P-028 gate badge** (green/yellow/red):
   - Green: "Full assertion — sufficient peers."
   - Yellow: "Hedged — borderline peer count."
   - Red: "Suppressed — fewer than 3 data points. Gap claims blocked."
8. Point to the **gap practices list** and **peer count tile**.

**Rubric covered:** Signal Brief Artifact Visibility — both briefs shown, confidence bars visible, AI maturity /3 visible

---

## STEP 4 — Show the Email and Simulate a Reply (90 seconds)

**On: Dashboard Tab 1 → Email Conversation tab**

1. Click **Email Conversation** tab.
2. Point to the **Send Receipt** at the top:
   - FROM: `onboarding@resend.dev`
   - TO: `gashawbekelek@gmail.com` (staff sink)
   - PROVIDER: `resend`
   - MSG ID: *(real Resend message ID — point to it)*
   - Say: "This email physically arrived in my Gmail inbox."
3. Point to the **email body** — subject line and first paragraph grounded in the signal brief.
4. Point to the **confidence band badge** on the email.
5. Click **💬 Simulate Prospect Reply**.
6. Watch the **Journey Banner** advance:
   **Email Sent → Prospect Replied → Qualified → Discovery Call Booked**
   Say: "Four stages advancing — each is a discrete CRM event."
7. Point to the **simulated reply text** appearing in the conversation.
8. Wait for the **SMS receipt** to appear (5–10 seconds):
   - PROVIDER: `africastalking`
   - MSG ID: *(real AT message ID)*
   - Say: "SMS follow-up fired automatically. Delivered to +251920531543. I received it on my phone."
9. Point to the **Prospect Qualified** card — segment confirmed, confidence shown.

**Rubric covered:**
- End-to-End Conversion Flow (reply → qualified → booked, same prospect, visible)
- Email channel (Resend MSG ID on screen)
- SMS warm-lead channel (AT receipt on screen)

---

## STEP 5 — Show HubSpot CRM (45 seconds)

**On: Dashboard Tab 1 → HubSpot CRM tab**

1. Click **HubSpot CRM** tab.
2. Point to the **health pills**:
   - Green pill: "All fields populated — zero nulls."
   - Lightning bolt pill: "Session-current — written in this pipeline run, not a stale fixture."
3. Point to the **Lead Status Progression** stepper:
   - Step 1 (Attempted to Contact) = done (green) — set when pipeline ran
   - Step 2 (Connected) = current (blue) — set when Simulate Reply was clicked
   - Say: "This stepper reflects the real HubSpot hs_lead_status property."
4. Point to the **contact header**: Daniela Ruiz, CTO, Aurelia Health.
5. Point to the **stage badge**: Discovery Booked.
6. Point to the **fields grid** — call out:
   - `crunchbase_id` — data provenance anchor
   - `icp_segment` — classification result
   - `ai_maturity_score` — signal value
   - `calcom_booking_id` — links to Cal.com
   - `last_enriched_at` with ⚡ — confirms session-current

**Now switch to Tab 2 — HubSpot live portal**

7. Switch to `https://app-eu1.hubspot.com/contacts/`
8. Find **Daniela Ruiz** in the contacts list (or search for her).
9. Click her name to open the contact record.
10. Show the evaluator:
    - **Name**: Daniela Ruiz
    - **Email**: daniela@aureliahealth.dev
    - **Lead Status**: Connected *(or In Progress if booking advanced it)*
    - **Job Title**: Chief Technology Officer
    - **Company**: Aurelia Health
11. Say: "Same contact record. Same Lead Status value. Written by the dashboard pipeline 90 seconds ago."
12. Switch back to Tab 1.

**Rubric covered:** HubSpot CRM Artifact State — fully populated, session-current timestamp, real portal shown

---

## STEP 6 — Show Cal.com Booking (40 seconds)

**On: Dashboard Tab 1 → Cal.com Booking tab**

1. Click **Cal.com Booking** tab.
2. Point to the **green Confirmed banner**: "Discovery Call Confirmed."
3. Point to the **event details**:
   - Event type: *Discovery Call — Tenacious Consulting & Outsourcing*
   - Date and time (say them out loud)
   - Attendee: **Daniela Ruiz** *(name visible)*
   - Tenacious delivery lead email
4. Point to the **Booking ID** at the bottom of the card.
   Say: "Same booking ID shown in the HubSpot fields grid and the pipeline result line."
5. Point to the **context brief** section:
   - company_name, icp_segment, ai_maturity_score — embedded in meeting notes
6. Point to the **Cal.com confirmation email preview** at the bottom:
   - FROM: `booking@cal.com`
   - TO: `daniela@aureliahealth.dev`
   - SUBJECT: Confirmed: Discovery Call...
   - Date, time, reschedule link, booking reference visible

**Rubric covered:** Cal.com Booking Artifact State — confirmed booking, date/time/attendee/event type all visible

---

## STEP 7 — Show P-028 Fix and Benchmark Evidence (50 seconds)

**On: Dashboard Tab 1 → 📈 Benchmark & P-028 tab**

1. Click **📈 Benchmark & P-028** tab.
2. Point to the **4 metric tiles**:
   - 72.7% pass@1 / 150 simulations / $0.0199 / 106s p50
3. Point to the **P-028 delta row**:
   - Left: **40%** trigger rate (red) — before fix
   - Right: **0%** trigger rate (green) — after fix
   - p = 0.015 (Fisher exact)
   - Say: "Three lines of code in the email composer. Statistically significant."
4. Point to the **ablation table** — 3 conditions, winning row highlighted green.
5. Point to the **evidence graph** — 8 visible claims with source refs.
   Say: "15 traceable claims. Every claim in the decision memo is backed by a run ID."

**Rubric covered:** Fixed failure with statistical evidence (rubric bonus) + Benchmark score

---

## STEP 8 — Show Africa's Talking Proof (20 seconds, optional)

**On: Tab 3 — `https://account.africastalking.com/apps/gashaw/sms`**

1. Switch to the AT dashboard.
2. Click **SMS → Sent Messages**.
3. Show the sent message log — find the most recent entry to `+251920531543`.
4. Point to the message body: "Hi Daniela, thanks for replying — sending calendar link now. — Tenacious"
5. Say: "Live delivery, not sandbox. Delivered via Ethio Telecom."
6. Switch back to Tab 1.

**Rubric covered:** Demo Production Compliance (external verification of SMS channel)

---

## CLOSING — 35 seconds

**On: Dashboard Tab 1 — point to header tiles**

Say:
- "72.7% pass@1. 150 simulations. $0.0199 per run. P-028 fixed: 40%→0%, p=0.015."
- "What is not fixed: P-011, offshore objection, 44% trigger rate, ~$52,800/week pipeline cost."
- "Recommendation: pilot with Segment 3, 50 prospects/week, $150 budget, 12% reply gate by day 30."
- "TENACIOUS_LIVE is the only gate between this system and live outbound."

---

## RUBRIC SCORE — WHAT EARNS FULL MARKS

### ✅ End-to-End Conversion Flow — 5/5
| Requirement | Where shown | ✓/✗ |
|---|---|---|
| Signal-grounded outreach email | Email Conversation tab — body grounded in brief | ✓ |
| Prospect replies | Simulate Reply button → reply text appears | ✓ |
| Gets qualified | Journey Banner: Replied → Qualified stage | ✓ |
| Discovery call booking | Journey Banner: Discovery Call Booked + Cal.com tab | ✓ |
| Same prospect identity throughout | Daniela Ruiz name visible in all tabs | ✓ |
| Continuous lifecycle visible | 6-stage Journey Banner on screen the whole time | ✓ |

### ✅ Signal Brief Artifact Visibility — 5/5
| Requirement | Where shown | ✓/✗ |
|---|---|---|
| Hiring signal brief shown | Signal & Gap Briefs tab — left column | ✓ |
| Per-signal confidence scores visible | 5 colour-coded confidence bars | ✓ |
| AI maturity score visible with /3 denominator | AI Maturity card: "X / 3" | ✓ |
| Competitor gap brief shown | Signal & Gap Briefs tab — lower section | ✓ |
| Briefs are legible (not screenshots) | Live-rendered data from API | ✓ |

### ✅ HubSpot CRM Artifact State — 5/5
| Requirement | Where shown | ✓/✗ |
|---|---|---|
| Contact record displayed | HubSpot CRM tab + live portal | ✓ |
| Firmographic fields populated | firstname, lastname, company, jobtitle | ✓ |
| Enrichment fields populated | crunchbase_id, icp_segment, ai_maturity_score | ✓ |
| Session-current timestamp | ⚡ lightning bolt on last_enriched_at | ✓ |
| Not a stale prior session | Health pill: "Session-current enrichment" | ✓ |

### ✅ Cal.com Booking Artifact State — 5/5
| Requirement | Where shown | ✓/✗ |
|---|---|---|
| Booking confirmed | Green "Discovery Call Confirmed" banner | ✓ |
| Date visible | Cal.com Booking tab — date row | ✓ |
| Time visible | Cal.com Booking tab — time row | ✓ |
| Attendee name visible | "Daniela Ruiz" in attendee card | ✓ |
| Event type visible | "Discovery Call — Tenacious Consulting & Outsourcing" | ✓ |

### ✅ Demo Production Compliance — 5/5
| Requirement | How satisfied | ✓/✗ |
|---|---|---|
| Under 8 minutes | Timing guide totals exactly 8:00 | ✓ |
| No login required to view | Record as MP4 / upload to YouTube unlisted | ✓ |
| Grader can follow each section | Section headers called out verbally + tab names | ✓ |
| External tools shown | HubSpot portal + AT sent log = two real external verifications | ✓ |

---

## SCREEN SEQUENCE SUMMARY

```
Dashboard (no prospect)
  ↓ Step 1: Point to header tiles + sidebar (30s)
  ↓ Step 2: Click Aurelia Health → Run Pipeline → Journey Banner (2min)
  ↓ Step 3: Signal & Gap Briefs tab — briefs + confidence + AI score + P-028 badge (45s)
  ↓ Step 4: Email Conversation tab — receipt + body + Simulate Reply → Journey → SMS (90s)
  ↓ Step 5a: HubSpot CRM tab — fields + Lead Status stepper (30s)
  ↓ Step 5b: Switch to HubSpot portal — Daniela Ruiz contact record (20s)
  ↓ Step 6: Cal.com Booking tab — confirmed + details + preview (40s)
  ↓ Step 7: Benchmark & P-028 tab — tiles + ablation + evidence (50s)
  ↓ Step 8: Switch to AT dashboard — sent messages log (20s)
  ↓ Closing: Back to dashboard header tiles (35s)

Total: ~8:00
```

---

## COMMON MISTAKES THAT DROP MARKS

| Mistake | Rubric item hurt | Fix |
|---|---|---|
| Not scrolling down to show competitor gap brief | Signal Brief — drops to 3/5 | Scroll down in Signal & Gap Briefs tab to show both briefs |
| AI maturity score shown without the "/3" denominator | Signal Brief — grader may not see it | Zoom in on the AI Maturity card so "X / 3" is clearly readable |
| Switching away from HubSpot tab before timestamp is visible | HubSpot — drops to 3/5 | Pause on the ⚡ last_enriched_at field for 3 seconds |
| Showing HubSpot portal with old contacts only | HubSpot — drops to 1/5 | Run pipeline first in this session before recording |
| Not calling out Daniela Ruiz by name across tabs | End-to-End Flow — drops to 3/5 | Say "Daniela Ruiz" verbally every time you switch tabs |
| Forgetting to show Cal.com confirmation email preview | Cal.com — borderline | Scroll down in Cal.com tab to show preview at the bottom |
| Video over 8 minutes | Compliance — drops to 3/5 | Practise once with a timer. Cut AT tab visit if running long |
| Login wall on recording (e.g., HubSpot requires sign-in to view) | Compliance — 0/5 | Record your own screen, export as MP4, upload to YouTube unlisted |
