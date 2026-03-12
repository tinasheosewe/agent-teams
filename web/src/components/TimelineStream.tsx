import { useRef, useEffect, useCallback, useState, useMemo } from 'react'
import Markdown from 'react-markdown'
import type { WsEvent } from '../hooks/useWebSocket'

/* ─── Helpers ─── */
const PALETTE = ['#818cf8', '#34d399', '#fbbf24', '#f87171', '#60a5fa', '#a78bfa', '#fb923c', '#2dd4bf']

function hashIdx(name: string): number {
  let h = 0
  for (let i = 0; i < name.length; i++) h = name.charCodeAt(i) + ((h << 5) - h)
  return Math.abs(h) % PALETTE.length
}

function initials(name: string): string {
  return name.split(/[_\s-]+/).map(w => w[0]?.toUpperCase() ?? '').join('').slice(0, 2)
}

function relativeTime(ts: string): string {
  const d = new Date(ts)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

/* ─── Flatten events into timeline items ─── */
type TimelineItemKind =
  | 'step_start'
  | 'step_complete'
  | 'agent_message'
  | 'decision'
  | 'gate'
  | 'escalation'
  | 'system'

interface TimelineItem {
  kind: TimelineItemKind
  event: WsEvent
  stepName?: string
}

function buildTimeline(events: WsEvent[], filterStep: string | null): TimelineItem[] {
  const items: TimelineItem[] = []
  let currentStep: string | null = null

  for (const evt of events) {
    if (evt.type === 'workflow_step_start' && evt.data.step) {
      currentStep = String(evt.data.step)
      if (!filterStep || filterStep === currentStep) {
        items.push({ kind: 'step_start', event: evt, stepName: currentStep })
      }
      continue
    }

    if (evt.type === 'workflow_step_complete' && evt.data.step) {
      const step = String(evt.data.step)
      if (!filterStep || filterStep === step) {
        items.push({ kind: 'step_complete', event: evt, stepName: step })
      }
      if (currentStep === step) currentStep = null
      continue
    }

    // Skip cost_update from timeline
    if (evt.type === 'cost_update') continue
    // Skip workflow_complete (rendered separately)
    if (evt.type === 'workflow_complete') continue

    // If filtering by step, only include events from that step
    if (filterStep && currentStep !== filterStep) continue

    if (evt.type === 'agent_message') {
      items.push({ kind: 'agent_message', event: evt, stepName: currentStep ?? undefined })
    } else if (evt.type === 'decision_made') {
      items.push({ kind: 'decision', event: evt, stepName: currentStep ?? undefined })
    } else if (evt.type === 'forum_gate_result') {
      items.push({ kind: 'gate', event: evt, stepName: currentStep ?? undefined })
    } else if (evt.type === 'forum_escalation') {
      items.push({ kind: 'escalation', event: evt, stepName: currentStep ?? undefined })
    } else {
      items.push({ kind: 'system', event: evt, stepName: currentStep ?? undefined })
    }
  }

  return items
}

/* ─── Component ─── */
interface Props {
  events: WsEvent[]
  selectedStep: string | null
  onNavigateToDecision?: (decisionId: string) => void
}

export default function TimelineStream({ events, selectedStep, onNavigateToDecision }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const [isNearBottom, setIsNearBottom] = useState(true)

  const handleScroll = useCallback(() => {
    const el = containerRef.current
    if (!el) return
    setIsNearBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 80)
  }, [])

  useEffect(() => {
    if (isNearBottom) bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [events.length, isNearBottom])

  const items = useMemo(() => buildTimeline(events, selectedStep), [events, selectedStep])
  const hasComplete = events.some(e => e.type === 'workflow_complete')

  if (events.length === 0) {
    return (
      <div className="timeline-panel">
        <div className="timeline-empty">
          <div className="timeline-empty-icon">▸</div>
          <div className="timeline-empty-title">Launch a project to begin</div>
          <p className="timeline-empty-text">Activity will appear here in real time</p>
        </div>
      </div>
    )
  }

  return (
    <div className="timeline-panel" ref={containerRef} onScroll={handleScroll}>
      <div className="timeline">
        <div className="timeline-spine" />

        {items.map((item, i) => {
          switch (item.kind) {
            case 'step_start':
              return <StepDivider key={`s-${i}`} event={item.event} type="start" />
            case 'step_complete':
              return <StepDivider key={`s-${i}`} event={item.event} type="complete" />
            case 'agent_message':
              return <AgentMessageCard key={`m-${i}`} event={item.event} />
            case 'decision':
              return <DecisionCard key={`d-${i}`} event={item.event} onNavigate={onNavigateToDecision} />
            case 'gate':
              return <GateResultCard key={`g-${i}`} event={item.event} />
            case 'escalation':
              return <EscalationBanner key={`e-${i}`} event={item.event} />
            case 'system':
              return <SystemEvent key={`x-${i}`} event={item.event} />
            default:
              return null
          }
        })}

        {hasComplete && (
          <div className="timeline-complete">
            <div className="timeline-complete-icon">✓</div>
            <span>Workflow Complete</span>
            {events.filter(e => e.type === 'workflow_complete').map((e, i) => (
              <span key={i} className="timeline-complete-stats">
                {String(e.data.total_input_tokens)} in · {String(e.data.total_output_tokens)} out
              </span>
            ))}
          </div>
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  )
}

/* ─── Sub-components ─── */

function StepDivider({ event, type }: { event: WsEvent; type: 'start' | 'complete' }) {
  const d = event.data
  const name = String(d.step || '')
  const team = String(d.team || name)
  const color = PALETTE[hashIdx(team)]
  const fastTracked = type === 'complete' && d.fast_tracked

  return (
    <div className={`tl-divider tl-divider-${type}`}>
      <div className="tl-dot-lg" style={{ borderColor: color, background: type === 'complete' ? color : 'transparent' }}>
        {type === 'complete' ? (fastTracked ? '⚡' : '✓') : '▸'}
      </div>
      <span className="tl-divider-name">{name}</span>
      <span className="tl-divider-team" style={{ color }}>{team}</span>
      {d.attempt && Number(d.attempt) > 1 ? (
        <span className="tl-divider-attempt">attempt {String(d.attempt)}</span>
      ) : null}
      {fastTracked ? <span className="badge badge-neutral">skipped</span> : null}
      <span className="tl-divider-time">{relativeTime(event.timestamp)}</span>
    </div>
  )
}

function AgentMessageCard({ event }: { event: WsEvent }) {
  const d = event.data
  const name = String(d.agent || 'Agent')
  const color = PALETTE[hashIdx(name)]

  return (
    <div className="tl-card tl-card-message">
      <div className="tl-dot" />
      <div className="tl-card-inner">
        <div className="tl-card-avatar" style={{ background: color }}>{initials(name)}</div>
        <div className="tl-card-body">
          <div className="tl-card-header">
            <span className="tl-card-name">{name}</span>
            <span className="tl-card-time">{relativeTime(event.timestamp)}</span>
          </div>
          <div className="tl-card-content markdown-body">
            <Markdown>{String(d.content || '')}</Markdown>
          </div>
        </div>
      </div>
    </div>
  )
}

function DecisionCard({ event, onNavigate }: { event: WsEvent; onNavigate?: (id: string) => void }) {
  const d = event.data
  const conf = Number(d.confidence ?? 0)
  const confPct = (conf * 100).toFixed(0)
  const severity = conf < 0.4 ? 'critical' : conf < 0.6 ? 'warning' : 'normal'

  return (
    <div
      className={`tl-card tl-card-decision tl-decision-${severity}`}
      onClick={() => onNavigate?.(String(d.id ?? ''))}
    >
      <div className={`tl-dot tl-dot-decision tl-dot-${severity}`} />
      <div className="tl-card-inner">
        <div className="tl-decision-header">
          <span className="tl-decision-icon">✓</span>
          <span className="tl-decision-topic">{String(d.topic ?? 'Decision')}</span>
          <span className={`tl-decision-conf tl-conf-${severity}`}>{confPct}%</span>
        </div>
        <div className="tl-decision-bar">
          <div
            className={`tl-decision-fill tl-fill-${severity}`}
            style={{ width: `${conf * 100}%` }}
          />
        </div>
        {d.decision ? (
          <div className="tl-decision-text">{String(d.decision).slice(0, 200)}</div>
        ) : null}
        <div className="tl-decision-meta">
          <span>{String(d.team ?? '')}</span>
          <span>{relativeTime(event.timestamp)}</span>
        </div>
      </div>
    </div>
  )
}

function GateResultCard({ event }: { event: WsEvent }) {
  const d = event.data
  const passed = String(d.result ?? '').toLowerCase().includes('approv')

  return (
    <div className={`tl-card tl-card-gate tl-gate-${passed ? 'pass' : 'fail'}`}>
      <div className={`tl-dot tl-dot-gate ${passed ? 'tl-dot-pass' : 'tl-dot-fail'}`} />
      <div className="tl-card-inner">
        <div className="tl-gate-header">
          <span className="tl-gate-icon">{passed ? '✓' : '↩'}</span>
          <span className="tl-gate-name">Gate: {String(d.gate ?? '')}</span>
          <span className={`badge ${passed ? 'badge-success' : 'badge-danger'}`}>{String(d.result ?? '')}</span>
        </div>
        {d.notes ? <div className="tl-gate-notes">{String(d.notes)}</div> : null}
      </div>
    </div>
  )
}

function EscalationBanner({ event }: { event: WsEvent }) {
  return (
    <div className="tl-escalation">
      <div className="tl-dot tl-dot-escalation" />
      <div className="tl-escalation-inner">
        <span className="tl-escalation-icon">▲</span>
        <span>{String(event.data.message ?? '')}</span>
      </div>
    </div>
  )
}

function SystemEvent({ event }: { event: WsEvent }) {
  const d = event.data
  let icon = '·'
  let text = ''

  if (event.type === 'team_mode_selected') {
    icon = '◆'; text = `Mode: **${String(d.mode)}**`
  } else if (event.type === 'team_task_assigned') {
    icon = '▤'; text = `Tasks assigned`
  } else if (event.type === 'artifact_created') {
    icon = '□'; text = `Artifact **${String(d.artifact_type ?? d.name ?? '')}** created`
  } else if (event.type === 'agent_tool_call') {
    icon = '⚡'; text = `**${String(d.agent ?? '')}** → \`${String(d.tool ?? '')}\``
  } else if (event.type === 'team_round_start') {
    icon = '○'; text = `Round ${String(d.round ?? '')}`
  } else if (event.type === 'team_round_end') {
    const conf = Number(d.confidence ?? 0)
    icon = '●'; text = `Round complete — ${(conf * 100).toFixed(0)}% confidence`
  } else if (event.type === 'file_written') {
    icon = '▪'; text = `File written: \`${String(d.path ?? '')}\``
  } else if (event.type === 'user_input_received') {
    icon = '›'; text = `User: ${String(d.message ?? '')}`
  } else if (event.type === 'decision_superseded') {
    icon = '↻'; text = `Decision superseded`
  } else if (event.type === 'question_raised') {
    icon = '?'; text = `Question: ${String(d.question ?? '')}`
  } else if (event.type === 'forum_handoff') {
    icon = '→'; text = `Handoff`
  } else {
    text = Object.entries(d).filter(([, v]) => v != null).map(([k, v]) => `**${k}:** ${v}`).join(' · ')
  }

  return (
    <div className="tl-system">
      <div className="tl-dot tl-dot-system" />
      <span className="tl-system-icon">{icon}</span>
      <div className="tl-system-text markdown-body">
        <Markdown>{text}</Markdown>
      </div>
      <span className="tl-system-time">{relativeTime(event.timestamp)}</span>
    </div>
  )
}
