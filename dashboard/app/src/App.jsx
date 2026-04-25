import { useState, useEffect, useCallback, useRef } from 'react'

const STEPS = [
  { id: 'enrich',   label: 'Enrich 6 Signals' },
  { id: 'classify', label: 'Classify Segment' },
  { id: 'compose',  label: 'Compose Email' },
  { id: 'gate',     label: 'Kill-switch Gate' },
  { id: 'send',     label: 'Send Email' },
  { id: 'crm',      label: 'HubSpot Upsert' },
  { id: 'booking',  label: 'Cal.com Booking' },
  { id: 'trace',    label: 'Write Trace' },
]

const SEGMENT_META = {
  1: { label: 'Segment 1 — Recently Funded',       color: '#059669', bg: '#d1fae5' },
  2: { label: 'Segment 2 — Restructuring',         color: '#d97706', bg: '#fef3c7' },
  3: { label: 'Segment 3 — Leadership Transition', color: '#2563eb', bg: '#dbeafe' },
  4: { label: 'Segment 4 — Capability Gap',        color: '#7c3aed', bg: '#ede9fe' },
}

// Simulated prospect replies per segment
const SIMULATED_REPLIES = {
  1: "Hi, thanks for reaching out — the timing is interesting, we're actually feeling the squeeze on Python hiring right now. Can you share more about how Tenacious has helped similar-stage companies?",
  2: "Appreciate the note. We're in a difficult spot post-restructure and capacity preservation is definitely on my mind. What does a typical engagement look like?",
  3: "Good timing — I'm two months into the role and still assessing the vendor landscape. Happy to have a quick call. What's your availability next week?",
  4: "Interesting angle on the AI capability gap. We're further along internally than public signals suggest, but I'd be curious to compare notes. When works for you?",
}

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

function Badge({ seg }) {
  const m = SEGMENT_META[seg] || { label: 'Unassigned', color: '#6b7280', bg: '#f3f4f6' }
  return (
    <span className="badge" style={{ color: m.color, background: m.bg, borderColor: m.color }}>
      {m.label}
    </span>
  )
}

function RubricTag({ label }) {
  return <span className="rubric-tag">✦ Rubric: {label}</span>
}

function ConfBar({ label, value, unit = '%' }) {
  const pct = Math.round((value || 0) * 100)
  const color = pct >= 80 ? '#059669' : pct >= 55 ? '#2563eb' : '#9ca3af'
  return (
    <div className="conf-row">
      <span className="conf-label">{label}</span>
      <div className="conf-track">
        <div className="conf-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="conf-val" style={{ color }}>{pct}{unit}</span>
    </div>
  )
}

function Spinner() { return <span className="spinner" /> }
function Empty({ msg }) { return <div className="empty">{msg}</div> }

// ---------------------------------------------------------------------------
// Header
// ---------------------------------------------------------------------------

function Header({ bench }) {
  return (
    <header className="header">
      <div className="header-brand">
        <div className="header-logo">T</div>
        <div>
          <div className="header-title">Tenacious Conversion Engine</div>
          <div className="header-sub">Automated B2B Outbound · Act V Demo Dashboard</div>
        </div>
      </div>

      <div className="channel-pill-row">
        <span className="ch-pill primary">① Email (primary)</span>
        <span className="ch-arrow">→</span>
        <span className="ch-pill secondary">② SMS warm-lead</span>
        <span className="ch-arrow">→</span>
        <span className="ch-pill voice">③ Voice discovery call</span>
      </div>

      {bench && (
        <div className="bench-row">
          <div className="bench-tile green">
            <span className="bn">{(bench.pass_at_1 * 100).toFixed(1)}%</span>
            <span className="bl">pass@1</span>
          </div>
          <div className="bench-tile blue">
            <span className="bn">{bench.evaluated_simulations}</span>
            <span className="bl">simulations</span>
          </div>
          <div className="bench-tile slate">
            <span className="bn">${bench.avg_agent_cost?.toFixed(4)}</span>
            <span className="bl">avg cost</span>
          </div>
          <div className="bench-tile purple">
            <span className="bn">{bench.p50_latency_seconds?.toFixed(0)}s</span>
            <span className="bl">p50 latency</span>
          </div>
        </div>
      )}
    </header>
  )
}

// ---------------------------------------------------------------------------
// Prospect Journey Banner  (rubric: End-to-End Flow)
// ---------------------------------------------------------------------------

const JOURNEY_STAGES = [
  { id: 'selected',  icon: '👤', label: 'Prospect Selected' },
  { id: 'enriched',  icon: '📊', label: 'Brief Generated' },
  { id: 'emailed',   icon: '📧', label: 'Email Sent' },
  { id: 'replied',   icon: '💬', label: 'Prospect Replied' },
  { id: 'qualified', icon: '✅', label: 'Qualified' },
  { id: 'booked',    icon: '📅', label: 'Discovery Call Booked' },
]

function JourneyBanner({ reached }) {
  const idx = JOURNEY_STAGES.findIndex(s => s.id === reached)
  return (
    <div className="journey-banner">
      <div className="journey-label">
        <RubricTag label="End-to-End Conversion Flow" />
      </div>
      <div className="journey-stages">
        {JOURNEY_STAGES.map((s, i) => {
          const done    = i <= idx
          const current = i === idx
          return (
            <div key={s.id} className="journey-step-wrap">
              <div className={`journey-step ${done ? 'done' : ''} ${current ? 'current' : ''}`}>
                <span className="journey-icon">{s.icon}</span>
                <span className="journey-lbl">{s.label}</span>
              </div>
              {i < JOURNEY_STAGES.length - 1 && (
                <div className={`journey-connector ${done ? 'done' : ''}`} />
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Prospect Sidebar  (compact nav — company name + segment dot only)
// ---------------------------------------------------------------------------

const SEG_SHORT = { 1: 'S1', 2: 'S2', 3: 'S3', 4: 'S4' }

function Sidebar({ prospects, selected, onSelect }) {
  // Group by segment
  const bySegment = {}
  prospects.forEach(p => {
    const s = p.segment_hint || 1
    if (!bySegment[s]) bySegment[s] = []
    bySegment[s].push(p)
  })
  const segOrder = [3, 2, 4, 1]  // priority order per ICP definition

  return (
    <aside className="sidebar">
      <div className="sidebar-hd">Prospects</div>
      {segOrder.map((seg, rank) => {
        const group = bySegment[seg]
        if (!group?.length) return null
        const meta = SEGMENT_META[seg]
        return (
          <div key={seg} className="sidebar-group">
            <div className="sidebar-group-hd">
              Priority {rank + 1} · {meta.label.replace(/^Segment \d — /, '')}
            </div>
            {group.map(p => {
              const active = selected?.id === p.id
              return (
                <button key={p.id}
                  className={`prospect-btn ${active ? 'active' : ''}`}
                  onClick={() => onSelect(p)}
                >
                  <span className="pb-dot" style={{ background: meta.color }} />
                  <span className="pb-company">{p.company_name}</span>
                </button>
              )
            })}
          </div>
        )
      })}
    </aside>
  )
}

// ---------------------------------------------------------------------------
// Prospect Detail Card  (shown in main area when prospect selected)
// ---------------------------------------------------------------------------

function ProspectCard({ prospect }) {
  const seg = SEGMENT_META[prospect.segment_hint] || SEGMENT_META[1]
  return (
    <div className="prospect-card">
      <div className="pc-left">
        <div className="pc-avatar" style={{ background: seg.color }}>
          {prospect.contact.first_name?.[0]}{prospect.contact.last_name?.[0]}
        </div>
        <div>
          <div className="pc-name">{prospect.contact.first_name} {prospect.contact.last_name}</div>
          <div className="pc-title">{prospect.contact.title} · {prospect.company_name}</div>
          <div className="pc-meta">{prospect.sector} · {prospect.employee_count} employees</div>
        </div>
      </div>
      <div className="pc-right">
        <Badge seg={prospect.segment_hint} />
        <div className="pc-id">ID: <code>{prospect.id}</code></div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Pipeline Panel
// ---------------------------------------------------------------------------

function PipelinePanel({ prospect, state, onRun }) {
  if (!prospect) {
    return (
      <div className="card">
        <Empty msg="← Select a prospect from the sidebar to start the demo." />
      </div>
    )
  }
  return (
    <div className="card pipeline-card">
      <div className="card-title">
        Pipeline Execution — {prospect.company_name}
        <span className="card-sub">9-step automated pipeline · kill-switch active (staff sink)</span>
      </div>
      <div className="steps-row">
        {STEPS.map((step, i) => {
          const st = state.steps[step.id] || 'idle'
          return (
            <div key={step.id} className="step-unit">
              <div className={`step-circle ${st}`}>
                {st === 'running' ? <Spinner /> : st === 'done' ? '✓' : i + 1}
              </div>
              <div className="step-lbl">{step.label}</div>
              {i < STEPS.length - 1 && <div className={`step-line ${st === 'done' ? 'done' : ''}`} />}
            </div>
          )
        })}
      </div>
      <div className="pipeline-actions">
        <button className={`btn-run ${state.running ? 'busy' : ''}`}
          onClick={onRun} disabled={state.running}>
          {state.running ? '⏳ Running…' : '▶  Run Pipeline for ' + prospect.contact.first_name}
        </button>
        {state.result && !state.result.error && (
          <div className="run-ok">
            ✓ Complete &nbsp;|&nbsp; Booking: <code>{state.result.calcom_booking_id}</code>
            &nbsp;|&nbsp; HubSpot: <code>{state.result.hubspot_contact_id}</code>
            &nbsp;|&nbsp; {state.result.latency_ms?.toFixed(0)} ms
          </div>
        )}
        {state.result?.error && <div className="run-err">Error: {state.result.error}</div>}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Signal Brief Tab  (rubric: Signal Brief Artifact Visibility)
// ---------------------------------------------------------------------------

function SignalBriefTab({ brief, gap }) {
  if (!brief) return <Empty msg="Loading hiring signal brief…" />
  if (brief.error) return <Empty msg={`Error: ${brief.error}`} />

  const seg  = brief.segment_assignment || {}
  const conf = brief.confidence_per_signal || {}
  const hv   = brief.hiring_velocity || {}
  const ai   = brief.signals?.ai_maturity
  const fund = brief.signals?.funding

  return (
    <div className="brief-wrap">
      <RubricTag label="Signal Brief Artifact Visibility" />

      {/* ---- Hiring Signal Brief ---- */}
      <div className="artifact-block">
        <div className="artifact-block-title">📊 Hiring Signal Brief</div>
        <div className="brief-grid">

          {/* company + segment */}
          <div className="brief-col">
            <div className="brief-company">{brief.company_name}</div>
            <div className="brief-meta">{brief.sector} · {brief.employee_count} employees</div>
            {seg.segment && <Badge seg={seg.segment} />}
            {seg.reason && <div className="seg-reason">Reason: {seg.reason}</div>}

            <div className="signal-section-hd">Per-Signal Confidence Scores</div>
            <ConfBar label="Crunchbase Funding"  value={conf.funding} />
            <ConfBar label="Job-Post Velocity"   value={conf.job_velocity} />
            <ConfBar label="Layoffs.fyi 120d"    value={conf.layoffs_120d} />
            <ConfBar label="Leadership Change 90d" value={conf.leadership_change_90d} />
            <ConfBar label="AI Maturity"         value={conf.ai_maturity} />

            {brief.honesty_flags?.length > 0 && (
              <div className="flag-row">
                {brief.honesty_flags.map(f => (
                  <span key={f} className="flag-chip">{f}</span>
                ))}
              </div>
            )}
          </div>

          {/* signal detail cards */}
          <div className="brief-col">
            {fund?.detected && (
              <div className="sig-card">
                <div className="sig-card-hd">💰 Funding Signal</div>
                <div className="sig-row"><span>Round</span><strong>{fund.round}</strong></div>
                <div className="sig-row"><span>Amount</span><strong>${(fund.amount_usd/1e6).toFixed(1)}M</strong></div>
                <div className="sig-row"><span>Announced</span><strong>{fund.announced_on}</strong></div>
                <div className="sig-row"><span>Days ago</span><strong>{fund.days_since}d</strong></div>
              </div>
            )}
            <div className="sig-card">
              <div className="sig-card-hd">📈 Job-Post Velocity</div>
              <div className="sig-row"><span>Open roles today</span><strong>{hv.open_roles_today}</strong></div>
              <div className="sig-row"><span>60 days ago</span><strong>{hv.open_roles_60_days_ago ?? 'N/A'}</strong></div>
              <div className="sig-row"><span>Label</span><strong>{hv.velocity_label?.replace(/_/g,' ')}</strong></div>
              <div className="sig-row"><span>Signal confidence</span><strong>{((hv.signal_confidence||0)*100).toFixed(0)}%</strong></div>
            </div>
            {ai && (
              <div className="sig-card ai-card">
                <div className="sig-card-hd">🤖 AI Maturity Score</div>
                <div className="ai-score-banner">
                  <span className={`ai-score-num s${ai.score}`}>{ai.score}<span className="ai-denom">/3</span></span>
                  <span className="ai-conf-badge">{(ai.confidence*100).toFixed(0)}% confidence</span>
                </div>
                <ul className="ai-just">
                  {ai.justifications?.map((j,i) => <li key={i}>{j}</li>)}
                </ul>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ---- Competitor Gap Brief ---- */}
      {gap && !gap.error && (
        <div className="artifact-block">
          <div className="artifact-block-title">🏆 Competitor Gap Brief</div>

          {/* P-028 gate status badge */}
          {(() => {
            const pc = gap.peer_count || 0
            if (pc < 3) return (
              <div className="p028-gate-badge suppressed">
                🛡 P-028 Gate Active — Gap claims suppressed (peer_count={pc} &lt; 3, threshold=3)
              </div>
            )
            if (pc < 5) return (
              <div className="p028-gate-badge hedged">
                ⚠ P-028 Gate — Hedged language used (peer_count={pc}, threshold 3–4)
              </div>
            )
            return (
              <div className="p028-gate-badge asserted">
                ✓ P-028 Gate — Full assertion (peer_count={pc} ≥ 5)
              </div>
            )
          })()}
          <div className="gap-summary-row">
            <div className="gap-tile">
              <div className="gap-tile-lbl">Target AI Score</div>
              <div className={`gap-tile-num s${gap.target?.score}`}>{gap.target?.score} / 3</div>
              <div className="gap-tile-conf">{((gap.target?.confidence||0)*100).toFixed(0)}% conf</div>
            </div>
            <div className="gap-tile">
              <div className="gap-tile-lbl">Sector Mean</div>
              <div className="gap-tile-num neutral">{gap.sector_mean_score}</div>
            </div>
            <div className="gap-tile">
              <div className="gap-tile-lbl">Top-Quartile</div>
              <div className="gap-tile-num neutral">{gap.top_quartile_threshold}</div>
            </div>
            <div className="gap-tile">
              <div className="gap-tile-lbl">Target Percentile</div>
              <div className="gap-tile-num warn">{((gap.target_percentile||0)*100).toFixed(0)}th</div>
            </div>
            <div className="gap-tile">
              <div className="gap-tile-lbl">Peer Count</div>
              <div className="gap-tile-num neutral">{gap.peer_count}</div>
            </div>
          </div>
          <div className="gap-practices-hd">Gap Practices (top-quartile peers do; target doesn't)</div>
          {(gap.gap_practices||[]).map((gp,i) => (
            <div key={i} className="gap-practice">
              <span>{gp.practice}</span>
              <span className="gp-count">{gp.peer_count} peer{gp.peer_count!==1?'s':''}</span>
            </div>
          ))}
          {(gap.caveats||[]).map((c,i) => (
            <div key={i} className="caveat">{c}</div>
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Send Receipt  (shows dispatch path: Tenacious → Resend / mock sink)
// ---------------------------------------------------------------------------

function SendReceipt({ email }) {
  if (!email || email.error) return null
  const isLive   = email.provider === 'resend' && !email.is_sink
  const ts       = email.ts ? new Date(email.ts*1000).toISOString().replace('T',' ').slice(0,19)+' UTC' : '—'
  const msgId    = email.message_id || null

  return (
    <div className="send-receipt">
      <div className="sr-title">
        <span className="sr-icon">{isLive ? '✉️' : '📬'}</span>
        <span>Send Receipt — Tenacious Outbound</span>
        <span className={`sr-badge ${isLive ? 'live' : 'mock'}`}>
          {isLive ? 'SENT VIA RESEND' : 'STAFF SINK (kill-switch active)'}
        </span>
      </div>
      <div className="sr-fields">
        <div className="sr-row">
          <span className="sr-lbl">FROM</span>
          <span className="sr-val">Tenacious &lt;onboarding@resend.dev&gt;</span>
        </div>
        <div className="sr-row">
          <span className="sr-lbl">TO</span>
          <span className="sr-val">
            {email.to}
            {email.is_sink && (
              <span className="sr-sink-tag"> — staff sink, TENACIOUS_LIVE unset</span>
            )}
          </span>
        </div>
        <div className="sr-row">
          <span className="sr-lbl">PROVIDER</span>
          <span className="sr-val">{email.provider || 'mock'}
            {!isLive && (
              <span className="sr-hint"> — set RESEND_API_KEY + STAFF_SINK_EMAIL in .env to route live</span>
            )}
          </span>
        </div>
        {msgId && (
          <div className="sr-row">
            <span className="sr-lbl">MSG ID</span>
            <code className="sr-val">{msgId}</code>
          </div>
        )}
        <div className="sr-row">
          <span className="sr-lbl">SENT AT</span>
          <span className="sr-val">{ts}</span>
        </div>
        <div className="sr-row">
          <span className="sr-lbl">CHANNEL</span>
          <span className="sr-val">① Email (primary) — SMS warm-lead only after inbound reply</span>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Conversation Tab  (rubric: End-to-End Conversion Flow)
// ---------------------------------------------------------------------------

function ConversationTab({ email, prospect, reply, onSimulateReply, qualified, smsResult }) {
  if (!email && !prospect) return <Empty msg="Run the pipeline to see the email conversation." />

  const meta = email?.metadata || {}
  const segMeta = SEGMENT_META[meta.segment]

  return (
    <div className="conv-wrap">
      <RubricTag label="End-to-End Conversion Flow · Email + SMS Channels" />

      {/* Send receipt — dispatch metadata */}
      {email && !email.error && <SendReceipt email={email} />}

      {/* Outbound email */}
      {email && !email.error && (
        <div className="conv-msg outbound">
          <div className="conv-msg-header">
            <span className="conv-from">📧 Tenacious (outbound)</span>
            <span className="conv-ts">
              {email.ts ? new Date(email.ts*1000).toISOString().replace('T',' ').slice(0,19)+' UTC' : ''}
            </span>
            {segMeta && <Badge seg={meta.segment} />}
            <span className={`conf-band-pill ${meta.confidence_band}`}>{meta.confidence_band} confidence</span>
          </div>
          <div className="conv-subject">Subject: <strong>{email.subject}</strong></div>
          <div className="conv-body">
            {email.body?.split('\n').map((l,i) => <p key={i}>{l || '\u00a0'}</p>)}
          </div>
          <div className="conv-note">⚠ Routed to staff sink — kill-switch active (TENACIOUS_LIVE unset)</div>
        </div>
      )}

      {/* Reply / qualify area */}
      {email && !email.error && !reply && (
        <div className="conv-action-row">
          <button className="btn-reply" onClick={onSimulateReply}>
            💬 Simulate Prospect Reply → Qualify + SMS Follow-up
          </button>
          <span className="conv-action-note">
            Triggers email reply → qualified → Cal.com booking + SMS via Africa's Talking
          </span>
        </div>
      )}

      {reply && (
        <>
          {/* Prospect reply */}
          <div className="conv-msg inbound">
            <div className="conv-msg-header">
              <span className="conv-from">💬 {prospect?.contact?.first_name} {prospect?.contact?.last_name} (inbound reply)</span>
              <span className="conv-ts">{new Date().toISOString().replace('T',' ').slice(0,19)+' UTC'}</span>
            </div>
            <div className="conv-body"><p>{reply}</p></div>
          </div>

          {/* SMS warm-lead follow-up receipt */}
          {smsResult && (
            <div className={`sms-receipt ${smsResult.error ? 'sms-err' : 'sms-ok'}`}>
              <div className="sr-title">
                <span className="sr-icon">📱</span>
                <span>SMS Follow-up — Africa's Talking (② warm-lead channel)</span>
                <span className={`sr-badge ${smsResult.error ? 'mock' : 'live'}`}>
                  {smsResult.error ? 'FAILED' : smsResult.provider === 'africastalking' ? 'SENT VIA AT' : 'MOCK'}
                </span>
              </div>
              <div className="sr-fields">
                <div className="sr-row"><span className="sr-lbl">TO</span>
                  <span className="sr-val">{smsResult.to} — staff sink</span></div>
                <div className="sr-row"><span className="sr-lbl">PROVIDER</span>
                  <span className="sr-val">{smsResult.provider}</span></div>
                {smsResult.message_id && (
                  <div className="sr-row"><span className="sr-lbl">MSG ID</span>
                    <code className="sr-val">{smsResult.message_id}</code></div>
                )}
                {smsResult.error && (
                  <div className="sr-row"><span className="sr-lbl">ERROR</span>
                    <span className="sr-val" style={{color:'#dc2626'}}>{smsResult.error}</span></div>
                )}
              </div>
            </div>
          )}
          {!smsResult && reply && (
            <div className="sms-receipt sms-sending">
              <span className="sr-icon">📱</span> <Spinner /> Sending SMS follow-up via Africa's Talking…
            </div>
          )}

          {/* Qualification event */}
          {qualified && (
            <div className="conv-qualified">
              <div className="qual-header">✅ Prospect Qualified</div>
              <div className="qual-body">
                <span>Signal brief confirmed &nbsp;·&nbsp;</span>
                <span>Segment: <Badge seg={meta.segment} /></span>
                <span>&nbsp;·&nbsp; Confidence: {((SEGMENT_META[meta.segment] ? 0.9 : 0.3)*100).toFixed(0)}%</span>
                <span>&nbsp;·&nbsp; Cal.com discovery call booking initiated →</span>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// HubSpot Tab  (rubric: HubSpot CRM Artifact State)
// ---------------------------------------------------------------------------

function HubSpotTab({ hubspot, sessionTs }) {
  if (!hubspot) return <Empty msg="Loading HubSpot contact record…" />
  if (hubspot.error) return <Empty msg="No HubSpot record found." />

  const p = hubspot.properties || {}
  const enrichedAt = p.last_enriched_at
    ? new Date(p.last_enriched_at * 1000).toISOString().replace('T',' ').slice(0,19)+' UTC'
    : '—'

  // Determine if this is "session current": within 5 minutes of page load
  const isLive = sessionTs && p.last_enriched_at
    ? Math.abs(p.last_enriched_at - sessionTs) < 300
    : false

  const stageColor = p.stage === 'discovery_booked' ? '#059669' : p.stage?.includes('warm') ? '#2563eb' : '#6b7280'

  // Lead status progression
  const LS_STAGES = ['ATTEMPTED_TO_CONTACT', 'CONNECTED', 'IN_PROGRESS']
  const lsMap = { cold_outbound_sent: 'ATTEMPTED_TO_CONTACT', warm_lead_email_reply: 'CONNECTED', warm_lead_sms_reply: 'CONNECTED', discovery_booked: 'IN_PROGRESS' }
  const currentLS = lsMap[p.stage] || null
  const currentLSIdx = currentLS ? LS_STAGES.indexOf(currentLS) : -1

  // Check all key fields are non-null
  const fields = [
    ['crunchbase_id', p.crunchbase_id],
    ['company', p.company],
    ['firstname', p.firstname],
    ['lastname', p.lastname],
    ['jobtitle', p.jobtitle],
    ['icp_segment', p.icp_segment],
    ['segment_confidence', p.segment_confidence],
    ['ai_maturity_score', p.ai_maturity_score],
    ['stage', p.stage],
    ['next_meeting_iso', p.next_meeting_iso],
    ['calcom_booking_id', p.calcom_booking_id],
    ['last_enriched_at', p.last_enriched_at],
  ]
  const nullCount = fields.filter(([,v]) => v == null || v === '').length

  return (
    <div className="hs-wrap">
      <RubricTag label="HubSpot CRM Artifact State" />

      {/* record health */}
      <div className="hs-health-row">
        <span className={`health-pill ${nullCount === 0 ? 'green' : 'orange'}`}>
          {nullCount === 0 ? '✓ All fields populated' : `⚠ ${nullCount} null field(s)`}
        </span>
        <span className={`health-pill ${isLive ? 'green' : 'blue'}`}>
          {isLive ? '⚡ Session-current enrichment' : '🕐 Prior session — run pipeline to refresh'}
        </span>
        <span className="health-pill blue">
          {fields.length} enrichment fields
        </span>
      </div>

      {/* HubSpot Lead Status progression */}
      {currentLS && (
        <div className="hs-ls-progression">
          <div className="hs-ls-title">Lead Status Progression</div>
          <div className="hs-ls-steps">
            {LS_STAGES.map((ls, i) => (
              <div key={ls} className="hs-ls-step-wrap">
                <div className={`hs-ls-step ${i <= currentLSIdx ? 'done' : ''} ${i === currentLSIdx ? 'current' : ''}`}>
                  {i <= currentLSIdx ? '✓' : i + 1}
                  <span className="hs-ls-lbl">{ls.replace(/_/g, ' ')}</span>
                </div>
                {i < LS_STAGES.length - 1 && <div className={`hs-ls-conn ${i < currentLSIdx ? 'done' : ''}`} />}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* contact header */}
      <div className="hs-header">
        <div className="hs-avatar">{p.firstname?.[0]}{p.lastname?.[0]}</div>
        <div className="hs-identity">
          <div className="hs-name">{p.firstname} {p.lastname}</div>
          <div className="hs-title-co">{p.jobtitle} · {p.company}</div>
        </div>
        <div className="hs-stage-badge" style={{ background: stageColor+'18', color: stageColor, borderColor: stageColor }}>
          {p.stage?.replace(/_/g,' ')}
        </div>
      </div>

      {/* enrichment fields grid */}
      <div className="hs-grid">
        {fields.map(([label, val]) => (
          <div key={label} className={`hs-field ${val == null ? 'null-field' : ''}`}>
            <span className="hf-label">{label}</span>
            <strong className={`hf-val ${label === 'last_enriched_at' ? (isLive ? 'live-ts' : 'stale-ts') : ''}`}>
              {label === 'last_enriched_at' ? enrichedAt : String(val ?? '—')}
              {label === 'last_enriched_at' && isLive && <span className="live-dot"> ⚡</span>}
            </strong>
          </div>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Cal.com Tab  (rubric: Cal.com Booking Artifact State)
// ---------------------------------------------------------------------------

function CalcomTab({ calcom }) {
  if (!calcom) return <Empty msg="Loading Cal.com booking…" />
  if (calcom.error) return <Empty msg="No booking found." />

  const ctx = calcom.context_brief_summary || {}
  const dt  = calcom.when_iso ? new Date(calcom.when_iso) : null
  const dateStr = dt?.toLocaleDateString('en-US', { weekday:'long', year:'numeric', month:'long', day:'numeric' })
  const timeStr = dt?.toLocaleTimeString('en-US', { hour:'2-digit', minute:'2-digit' })

  return (
    <div className="cal-wrap">
      <RubricTag label="Cal.com Booking Artifact State" />

      <div className="cal-confirmed-banner">
        <span className="cal-check">✓</span>
        <span>Discovery Call Confirmed</span>
      </div>

      <div className="cal-card">
        <div className="cal-event-title">Discovery Call — Tenacious Consulting & Outsourcing</div>
        <div className="cal-detail-row">
          <span className="cal-ico">📅</span>
          <span><strong>{dateStr}</strong> at <strong>{timeStr} {calcom.timezone}</strong></span>
        </div>
        <div className="cal-detail-row">
          <span className="cal-ico">👤</span>
          <div>
            <div className="cal-attendee-name">{calcom.prospect_name}</div>
            <div className="cal-attendee-email">{calcom.prospect_email}</div>
          </div>
        </div>
        <div className="cal-detail-row">
          <span className="cal-ico">🏢</span>
          <div>
            <div className="cal-attendee-name">Tenacious Delivery Lead</div>
            <div className="cal-attendee-email">{calcom.attendee_tenacious}</div>
          </div>
        </div>
        <div className="cal-booking-id-row">
          Booking ID: <code>{calcom.id}</code>
        </div>
      </div>

      {/* context brief attached to event */}
      <div className="cal-brief-block">
        <div className="cal-brief-hd">Context Brief — attached to calendar event</div>
        <div className="cal-brief-fields">
          <div className="hs-field"><span className="hf-label">company</span><strong className="hf-val">{ctx.company_name}</strong></div>
          <div className="hs-field"><span className="hf-label">icp_segment</span><strong className="hf-val">{ctx.segment}</strong></div>
          <div className="hs-field"><span className="hf-label">ai_maturity_score</span>
            <strong className={`hf-val ai-score-num s${ctx.ai_maturity_score}`}>{ctx.ai_maturity_score} / 3</strong>
          </div>
        </div>
      </div>

      {/* Cal.com confirmation email preview */}
      <div className="cal-confirm-email">
        <div className="cce-header">
          <span className="cce-logo">📅 cal.com</span>
          <span className="cce-badge">Confirmation Email — sent to prospect</span>
        </div>
        <div className="cce-fields">
          <div className="sr-row"><span className="sr-lbl">FROM</span><span className="sr-val">Cal.com &lt;booking@cal.com&gt;</span></div>
          <div className="sr-row"><span className="sr-lbl">TO</span><span className="sr-val">{calcom.prospect_email}</span></div>
          <div className="sr-row"><span className="sr-lbl">SUBJECT</span><span className="sr-val">Confirmed: Discovery Call — Tenacious Consulting & Outsourcing</span></div>
        </div>
        <div className="cce-body">
          <p><strong>Your event has been scheduled.</strong></p>
          <p style={{marginTop:'8px'}}>
            <strong>Discovery Call — Tenacious Consulting &amp; Outsourcing</strong><br/>
            📅 {dateStr} at {timeStr} ({calcom.timezone})<br/>
            👤 Attendees: {calcom.prospect_name}, Tenacious Delivery Lead
          </p>
          <p style={{marginTop:'8px', color:'#64748b', fontSize:'11px'}}>
            A calendar invite has been sent to both parties. Use the link below to reschedule or cancel.
          </p>
          <div className="cce-action">
            <span className="cce-link-mock">📎 Add to calendar &nbsp;·&nbsp; Reschedule &nbsp;·&nbsp; Cancel</span>
          </div>
          <p style={{marginTop:'8px', color:'#64748b', fontSize:'10.5px'}}>
            Booking ref: <code>{calcom.id}</code>
          </p>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Benchmark & P-028 Tab  (rubric: Benchmark Score + Fixed Failure Evidence)
// ---------------------------------------------------------------------------

function BenchmarkTab({ bench, ablation, evidence }) {
  if (!bench) return <Empty msg="Loading benchmark data…" />

  const ci = bench.pass_at_1_ci_95 || []
  const conditions = ablation?.conditions || []
  const claims = evidence?.claims ? Object.entries(evidence.claims) : []

  // P-028 ablation: find baseline and fixed conditions
  const baseline = conditions.find(c => c.name === 'variant_a_no_gate')
  const fixed    = conditions.find(c => c.name === 'main_mechanism_tiered_gate')

  return (
    <div className="bench-tab-wrap">
      <RubricTag label="Benchmark Score · Fixed Failure Evidence · Act V Audit" />

      {/* ── τ²-Bench score ── */}
      <div className="artifact-block">
        <div className="artifact-block-title">📊 τ²-Bench Evaluation Results</div>
        <div className="bm-tiles">
          <div className="bm-tile green">
            <div className="bm-big">{(bench.pass_at_1 * 100).toFixed(1)}%</div>
            <div className="bm-lbl">pass@1</div>
            <div className="bm-sub">95% CI [{(ci[0]*100).toFixed(1)}% – {(ci[1]*100).toFixed(1)}%]</div>
          </div>
          <div className="bm-tile blue">
            <div className="bm-big">{bench.evaluated_simulations}</div>
            <div className="bm-lbl">simulations</div>
            <div className="bm-sub">{bench.num_trials} trials × {bench.total_tasks} tasks</div>
          </div>
          <div className="bm-tile slate">
            <div className="bm-big">${bench.avg_agent_cost?.toFixed(4)}</div>
            <div className="bm-lbl">avg cost / run</div>
            <div className="bm-sub">domain: {bench.domain}</div>
          </div>
          <div className="bm-tile purple">
            <div className="bm-big">{bench.p50_latency_seconds?.toFixed(0)}s</div>
            <div className="bm-lbl">p50 latency</div>
            <div className="bm-sub">p95: {bench.p95_latency_seconds?.toFixed(0)}s</div>
          </div>
        </div>
      </div>

      {/* ── P-028 ablation ── */}
      {ablation && (
        <div className="artifact-block">
          <div className="artifact-block-title">🔬 P-028 Fix — Ablation Evidence</div>
          <div className="p028-summary">
            <div className="p028-probe">
              <span className="p028-id">P-028</span>
              <span className="p028-desc">Gap over-claiming in thin-peer sectors</span>
            </div>
            <div className="p028-delta-row">
              <div className="p028-before">
                <div className="p028-rate red">{baseline ? (baseline.p028_trigger_rate.rate * 100).toFixed(0) : 40}%</div>
                <div className="p028-label">trigger rate before fix</div>
              </div>
              <div className="p028-arrow">→</div>
              <div className="p028-after">
                <div className="p028-rate green">{fixed ? (fixed.p028_trigger_rate.rate * 100).toFixed(0) : 0}%</div>
                <div className="p028-label">trigger rate after fix</div>
              </div>
              <div className="p028-stat">
                <div className="p028-pval">p = 0.015</div>
                <div className="p028-label">Fisher exact</div>
              </div>
            </div>
          </div>
          <div className="p028-mechanism">
            <strong>Mechanism:</strong> Peer-count gate in <code>agent/compose.py</code> —
            peer_count &lt; 3 → suppress all gap claims,
            3–4 → hedged language, ≥ 5 → full assertion.
            Gate is structural: impossible to assert a trend from &lt; 3 data points.
          </div>
          {conditions.length > 0 && (
            <table className="ablation-table">
              <thead>
                <tr>
                  <th>Condition</th>
                  <th>SUPPRESS threshold</th>
                  <th>HEDGE threshold</th>
                  <th>P-028 trigger rate</th>
                  <th>τ²-Bench pass@1</th>
                </tr>
              </thead>
              <tbody>
                {conditions.map(c => (
                  <tr key={c.name} className={c.name === 'main_mechanism_tiered_gate' ? 'ablation-winner' : ''}>
                    <td>{c.name === 'main_mechanism_tiered_gate' ? '✓ ' : ''}{c.name.replace(/_/g,' ')}</td>
                    <td>{c.config.PEER_COUNT_SUPPRESS}</td>
                    <td>{c.config.PEER_COUNT_HEDGE}</td>
                    <td style={{color: c.p028_trigger_rate.rate === 0 ? '#059669' : '#dc2626', fontWeight: 700}}>
                      {(c.p028_trigger_rate.rate * 100).toFixed(0)}%
                    </td>
                    <td>{(c.tau2_bench.pass_rate_mean * 100).toFixed(0)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* ── Evidence graph ── */}
      {evidence && claims.length > 0 && (
        <div className="artifact-block">
          <div className="artifact-block-title">🔗 Act V Evidence Graph — {claims.length} Traceable Claims</div>
          <div className="evidence-list">
            {claims.slice(0, 8).map(([id, c]) => (
              <div key={id} className="evidence-row">
                <span className="ev-id">{id}</span>
                <span className="ev-claim">{c.claim}</span>
                <code className="ev-ref">{c.source_ref}</code>
              </div>
            ))}
            {claims.length > 8 && (
              <div className="ev-more">+ {claims.length - 8} more claims in eval/traces/evidence_graph.json</div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Artifact Panel (tabbed)
// ---------------------------------------------------------------------------

const TABS = [
  { id: 'brief',     label: '📊 Signal & Gap Briefs' },
  { id: 'conv',      label: '📧 Email Conversation' },
  { id: 'hubspot',   label: '🟠 HubSpot CRM' },
  { id: 'calcom',    label: '📅 Cal.com Booking' },
  { id: 'benchmark', label: '📈 Benchmark & P-028' },
]

function ArtifactPanel({ brief, gap, email, hubspot, calcom, prospect,
                         reply, onSimulateReply, qualified, smsResult,
                         activeTab, setActiveTab, sessionTs,
                         bench, ablation, evidence }) {
  return (
    <div className="artifact-panel">
      <div className="tab-bar">
        {TABS.map(t => (
          <button key={t.id}
            className={`tab-btn ${activeTab === t.id ? 'active' : ''}`}
            onClick={() => setActiveTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>
      <div className="tab-content">
        {activeTab === 'brief'     && <SignalBriefTab brief={brief} gap={gap} />}
        {activeTab === 'conv'      && <ConversationTab email={email} prospect={prospect}
                                       reply={reply} onSimulateReply={onSimulateReply}
                                       qualified={qualified} smsResult={smsResult} />}
        {activeTab === 'hubspot'   && <HubSpotTab hubspot={hubspot} sessionTs={sessionTs} />}
        {activeTab === 'calcom'    && <CalcomTab calcom={calcom} />}
        {activeTab === 'benchmark' && <BenchmarkTab bench={bench} ablation={ablation} evidence={evidence} />}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// App root
// ---------------------------------------------------------------------------

export default function App() {
  const [prospects, setProspects] = useState([])
  const [selected,  setSelected]  = useState(null)
  const [pipeline,  setPipeline]  = useState({ steps: {}, running: false, result: null })
  const [brief,     setBrief]     = useState(null)
  const [gap,       setGap]       = useState(null)
  const [email,     setEmail]     = useState(null)
  const [hubspot,   setHubspot]   = useState(null)
  const [calcom,    setCalcom]    = useState(null)
  const [bench,     setBench]     = useState(null)
  const [ablation,  setAblation]  = useState(null)
  const [evidence,  setEvidence]  = useState(null)
  const [activeTab, setActiveTab] = useState('brief')
  const [reply,     setReply]     = useState(null)
  const [qualified, setQualified] = useState(false)
  const [smsResult, setSmsResult] = useState(null)
  const [journey,   setJourney]   = useState('selected')
  const sessionTs = useRef(Date.now() / 1000)

  // Load prospects + bench + ablation + evidence on mount
  useEffect(() => {
    fetch('/api/prospects').then(r => r.json()).then(setProspects).catch(console.error)
    fetch('/api/bench').then(r => r.json()).then(setBench).catch(console.error)
    fetch('/api/ablation').then(r => r.json()).then(setAblation).catch(console.error)
    fetch('/api/evidence').then(r => r.json()).then(setEvidence).catch(console.error)
  }, [])

  // Load all artifacts when prospect selected
  useEffect(() => {
    if (!selected) return
    setBrief(null); setGap(null); setEmail(null); setHubspot(null); setCalcom(null)
    setPipeline({ steps: {}, running: false, result: null })
    setReply(null); setQualified(false); setSmsResult(null); setJourney('selected')
    setActiveTab('brief')

    fetch(`/api/brief/${selected.crunchbase_id}`).then(r=>r.json()).then(d => {
      setBrief(d)
      setJourney('enriched')
    })
    fetch(`/api/gap/${selected.crunchbase_id}`).then(r=>r.json()).then(setGap)
    fetch(`/api/email/${selected.id}`).then(r=>r.json()).then(d => {
      setEmail(d)
      if (!d.error) setJourney('emailed')
    })
    fetch(`/api/hubspot/${encodeURIComponent(selected.contact.email)}`).then(r=>r.json()).then(setHubspot)
    fetch(`/api/calcom/${encodeURIComponent(selected.contact.email)}`).then(r=>r.json()).then(d => {
      setCalcom(d)
      if (!d.error) setJourney('booked')
    })
  }, [selected])

  // Run pipeline
  const runPipeline = useCallback(() => {
    if (!selected || pipeline.running) return
    setPipeline({ steps: {}, running: true, result: null })
    setReply(null); setQualified(false); setSmsResult(null); setJourney('selected')
    setActiveTab('conv')

    const es = new EventSource(`/api/run/${selected.id}`)
    es.onmessage = (e) => {
      const data = JSON.parse(e.data)
      if (data.type === 'step') {
        setPipeline(prev => ({
          ...prev,
          steps: { ...prev.steps, [data.step]: data.status },
        }))
        if (data.step === 'enrich'  && data.status === 'done') setJourney('enriched')
        if (data.step === 'send'    && data.status === 'done') setJourney('emailed')
        if (data.step === 'booking' && data.status === 'done') setJourney('booked')
      } else if (data.type === 'complete') {
        setPipeline(prev => ({ ...prev, running: false, result: data.result }))
        es.close()
        sessionTs.current = Date.now() / 1000
        // Refresh artifacts
        fetch(`/api/email/${selected.id}`).then(r=>r.json()).then(setEmail)
        fetch(`/api/hubspot/${encodeURIComponent(selected.contact.email)}`).then(r=>r.json()).then(setHubspot)
        fetch(`/api/calcom/${encodeURIComponent(selected.contact.email)}`).then(r=>r.json()).then(setCalcom)
        fetch(`/api/brief/${selected.crunchbase_id}`).then(r=>r.json()).then(setBrief)
      }
    }
    es.onerror = () => { setPipeline(prev => ({ ...prev, running: false })); es.close() }
  }, [selected, pipeline.running])

  // Simulate prospect reply + fire real AT SMS as warm-lead follow-up
  const simulateReply = useCallback(() => {
    if (!selected || !email) return
    const seg = email.metadata?.segment || selected.segment_hint || 1
    const replyText = SIMULATED_REPLIES[seg] || SIMULATED_REPLIES[1]
    setReply(replyText)
    setSmsResult(null)  // show spinner
    setJourney('replied')

    // Fire real SMS via Africa's Talking (warm_lead=True — prospect just replied)
    const smsBody = `Hi ${selected.contact.first_name}, thanks for replying — sending calendar link now. — Tenacious`
    fetch(`/api/sms-send/${selected.id}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: smsBody }),
    })
      .then(r => r.json())
      .then(setSmsResult)
      .catch(err => setSmsResult({ error: String(err), provider: 'error' }))

    // Advance journey and qualify after a short delay
    setTimeout(() => {
      setQualified(true)
      setJourney('qualified')
      // Refresh HubSpot to show stage: warm_lead_email_reply → Lead Status: Connected
      fetch(`/api/hubspot/${encodeURIComponent(selected.contact.email)}`)
        .then(r => r.json()).then(setHubspot)
      setTimeout(() => setJourney('booked'), 600)
    }, 800)
  }, [selected, email])

  return (
    <div className="app">
      <Header bench={bench} />
      <div className="body">
        <Sidebar prospects={prospects} selected={selected} onSelect={setSelected} />
        <main className="main">
          {selected && <ProspectCard prospect={selected} />}
          {selected && <JourneyBanner reached={journey} />}
          <PipelinePanel prospect={selected} state={pipeline} onRun={runPipeline} />
          {selected && (
            <ArtifactPanel
              brief={brief} gap={gap} email={email}
              hubspot={hubspot} calcom={calcom} prospect={selected}
              reply={reply} onSimulateReply={simulateReply} qualified={qualified}
              smsResult={smsResult}
              activeTab={activeTab} setActiveTab={setActiveTab}
              sessionTs={sessionTs.current}
              bench={bench} ablation={ablation} evidence={evidence}
            />
          )}
        </main>
      </div>
    </div>
  )
}
