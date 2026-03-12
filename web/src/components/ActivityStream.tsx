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

function extractTaskSummary(task: string): string {
  const req = task.match(/User's original request:\s*(.+)/)
  const purpose = task.match(/Your team's purpose:\s*(\S+)/)
  const produce = task.match(/Produce:\s*(.+)/)
  const parts: string[] = []
  if (req) parts.push(`"${req[1].trim()}"`)
  if (purpose) parts.push(`→ ${purpose[1]}`)
  if (produce) parts.push(`→ produce ${produce[1].trim()}`)
  return parts.length > 0 ? parts.join(' ') : task.slice(0, 120)
}

/* ─── Section / Round builders ─── */
interface TeamSection {
  id: string
  stepName: string
  teamName: string
  attempt: number
  status: 'in_progress' | 'completed' | 'failed'
  mode?: string
  task?: string
  fastTracked?: boolean
  events: WsEvent[]
}

function buildTeamSections(events: WsEvent[]): { sections: TeamSection[]; trailing: WsEvent[] } {
  const sections: TeamSection[] = []
  const trailing: WsEvent[] = []
  let current: TeamSection | null = null

  for (const evt of events) {
    if (evt.type === 'workflow_step_start' && evt.data.step) {
      current = {
        id: `${evt.data.step}-${evt.data.attempt ?? 1}`,
        stepName: String(evt.data.step),
        teamName: String(evt.data.team || evt.data.step),
        attempt: Number(evt.data.attempt ?? 1),
        status: 'in_progress',
        events: [evt],
      }
      sections.push(current)
      continue
    }

    if (evt.type === 'workflow_step_complete' && current && String(evt.data.step) === current.stepName) {
      current.status = 'completed'
      if (evt.data.fast_tracked) current.fastTracked = true
      current.events.push(evt)
      current = null
      continue
    }

    if (evt.type === 'team_mode_selected' && current) {
      current.mode = String(evt.data.mode)
      current.task = String(evt.data.task || '')
      current.events.push(evt)
      continue
    }

    if (current) current.events.push(evt)
    else trailing.push(evt)
  }

  return { sections, trailing }
}

interface RoundGroup { round: number; confidence?: number; events: WsEvent[] }

function buildRounds(events: WsEvent[]): RoundGroup[] {
  const rounds: RoundGroup[] = []
  let current: RoundGroup | null = null

  for (const evt of events) {
    if (evt.type === 'team_round_start') {
      current = { round: Number(evt.data.round ?? rounds.length + 1), events: [] }
      rounds.push(current)
      continue
    }
    if (evt.type === 'team_round_end' && current) {
      current.confidence = Number(evt.data.confidence ?? 0)
      current = null
      continue
    }
    if (current) current.events.push(evt)
  }

  return rounds
}

/* ─── Component ─── */
interface Props {
  events: WsEvent[]
  selectedStep: string | null
}

export default function ActivityStream({ events, selectedStep }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const [isNearBottom, setIsNearBottom] = useState(true)
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [collapsedRounds, setCollapsedRounds] = useState<Set<string>>(new Set())

  const handleScroll = useCallback(() => {
    const el = containerRef.current
    if (!el) return
    setIsNearBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 80)
  }, [])

  useEffect(() => {
    if (isNearBottom) bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [events.length, isNearBottom])

  const { sections, trailing } = useMemo(() => buildTeamSections(events), [events])
  const visible = selectedStep ? sections.filter(s => s.stepName === selectedStep) : sections

  const toggle = (id: string) => setCollapsed(prev => {
    const next = new Set(prev)
    next.has(id) ? next.delete(id) : next.add(id)
    return next
  })

  const toggleRound = (key: string) => setCollapsedRounds(prev => {
    const next = new Set(prev)
    next.has(key) ? next.delete(key) : next.add(key)
    return next
  })

  if (events.length === 0) {
    return (
      <div className="empty-state stream-empty">
        <div className="empty-state-icon">▸</div>
        <div className="empty-state-title">Launch a project to begin</div>
        <p className="empty-state-text">Activity will appear here in real time.</p>
      </div>
    )
  }

  return (
    <div className="activity-stream" ref={containerRef} onScroll={handleScroll}>
      {!selectedStep && trailing.filter(e => e.type !== 'cost_update').map((evt, i) => (
        <SystemEventRow key={`t-${i}`} event={evt} />
      ))}

      {visible.map(section => {
        const open = !collapsed.has(section.id)
        const color = PALETTE[hashIdx(section.teamName)]
        const rounds = buildRounds(section.events)

        if (section.fastTracked) {
          return (
            <div className="section fast-tracked" key={section.id}>
              <div className="section-header">
                <span className="section-dot" style={{ background: color }} />
                <span className="section-name">{section.stepName}</span>
                <span className="badge badge-neutral">skipped</span>
                <span className="fast-icon">⚡</span>
              </div>
            </div>
          )
        }

        return (
          <div className="section" key={section.id}>
            <div className="section-header" onClick={() => toggle(section.id)}>
              <span className="section-dot" style={{ background: color }} />
              <span className="section-name">{section.stepName}</span>
              <span className="section-team">{section.teamName}</span>
              {section.attempt > 1 && <span className="section-attempt">attempt {section.attempt}</span>}
              <span className={`badge ${section.status === 'completed' ? 'badge-success' : section.status === 'failed' ? 'badge-danger' : 'badge-info'}`}>
                {section.status === 'in_progress' ? 'running' : section.status}
              </span>
              {section.mode && <span className="mode-pill">{section.mode}</span>}
              <span className={`chevron ${open ? 'open' : ''}`}>›</span>
            </div>

            {open && (
              <div className="section-body">
                {section.mode && section.task && (
                  <div className="task-summary">
                    <span className="mode-pill">{section.mode}</span>
                    <span>{extractTaskSummary(section.task)}</span>
                  </div>
                )}

                {rounds.map(round => {
                  const rk = `${section.id}-r${round.round}`
                  const rOpen = !collapsedRounds.has(rk)
                  return (
                    <div className="round" key={rk}>
                      <div className="round-divider" onClick={() => toggleRound(rk)}>
                        <span className="round-label">{rOpen ? '▾' : '▸'} Round {round.round}</span>
                        {round.confidence != null && (
                          <span className={`round-conf ${round.confidence >= 0.8 ? 'high' : round.confidence >= 0.5 ? 'mid' : 'low'}`}>
                            {(round.confidence * 100).toFixed(0)}%
                          </span>
                        )}
                      </div>
                      {rOpen && round.events.map((evt, j) => (
                        <EventRow key={j} event={evt} teamColor={color} />
                      ))}
                    </div>
                  )
                })}

                {section.events
                  .filter(e =>
                    !['workflow_step_start', 'workflow_step_complete', 'team_mode_selected',
                      'team_round_start', 'team_round_end', 'cost_update'].includes(e.type) &&
                    !rounds.some(r => r.events.includes(e))
                  )
                  .map((evt, j) => <EventRow key={`x-${j}`} event={evt} teamColor={color} />)}

                {section.events.filter(e => e.type === 'forum_gate_result').map((evt, j) => (
                  <GateCard key={`g-${j}`} event={evt} />
                ))}
              </div>
            )}
          </div>
        )
      })}

      {events.some(e => e.type === 'workflow_complete') && (
        <div className="workflow-done">
          <span className="workflow-done-icon">✓</span>
          <span>Workflow Complete</span>
          {events.filter(e => e.type === 'workflow_complete').map((e, i) => (
            <span key={i} className="workflow-done-stats">
              {String(e.data.total_input_tokens)} in · {String(e.data.total_output_tokens)} out
            </span>
          ))}
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  )
}

/* ─── Sub-components ─── */

function EventRow({ event, teamColor }: { event: WsEvent; teamColor: string }) {
  const d = event.data

  if (event.type === 'agent_message') {
    const name = String(d.agent || 'Agent')
    return (
      <div className="msg">
        <div className="msg-avatar" style={{ background: teamColor }}>{initials(name)}</div>
        <div className="msg-body">
          <div className="msg-header">
            <span className="msg-name">{name}</span>
            <span className="msg-time">{new Date(event.timestamp).toLocaleTimeString()}</span>
          </div>
          <div className="msg-text markdown-body">
            <Markdown>{String(d.content || '')}</Markdown>
          </div>
        </div>
      </div>
    )
  }

  if (event.type === 'team_mode_selected') {
    return (
      <div className="sys-event">
        <span className="sys-icon">◆</span>
        <span>Mode: <strong>{String(d.mode)}</strong></span>
      </div>
    )
  }

  if (event.type === 'team_task_assigned') {
    return (
      <div className="sys-event">
        <span className="sys-icon">▤</span>
        <div className="markdown-body">
          <Markdown>{`**Tasks assigned:**\n\`\`\`json\n${JSON.stringify(d.subtasks, null, 2)}\n\`\`\``}</Markdown>
        </div>
      </div>
    )
  }

  if (event.type === 'decision_made') {
    return (
      <div className="sys-event">
        <span className="sys-icon">✓</span>
        <div className="markdown-body"><Markdown>{`**Decision:** ${d.decision}`}</Markdown></div>
      </div>
    )
  }

  if (event.type === 'artifact_created') {
    return (
      <div className="sys-event">
        <span className="sys-icon">□</span>
        <span>Artifact <strong>{String(d.artifact_type)}</strong> created</span>
      </div>
    )
  }

  if (event.type === 'forum_escalation') {
    return <div className="escalation">▲ {String(d.message)}</div>
  }

  if (event.type === 'agent_tool_call') {
    return (
      <div className="sys-event">
        <span className="sys-icon">⚡</span>
        <span><strong>{String(d.agent || '')}</strong> called <strong>{String(d.tool || '')}</strong></span>
      </div>
    )
  }

  return (
    <div className="sys-event">
      <span className="sys-icon">•</span>
      <div className="markdown-body">
        <Markdown>{'```json\n' + JSON.stringify(d, null, 2) + '\n```'}</Markdown>
      </div>
    </div>
  )
}

function GateCard({ event }: { event: WsEvent }) {
  const d = event.data
  const passed = String(d.result).toLowerCase().includes('pass')
  return (
    <div className={`gate ${passed ? 'passed' : 'failed'}`}>
      <span className="gate-icon">{passed ? '✓' : '↩'}</span>
      <span className="gate-label">Gate: {String(d.gate)}</span>
      <span className={`badge ${passed ? 'badge-success' : 'badge-danger'}`}>{String(d.result)}</span>
      {d.notes ? <div className="gate-notes">{String(d.notes)}</div> : null}
    </div>
  )
}

function SystemEventRow({ event }: { event: WsEvent }) {
  const d = event.data
  if (event.type === 'workflow_complete') return null

  let icon = '•'
  let text = ''
  if (event.type === 'workflow_step_start' && d.message) { icon = '▸'; text = String(d.message) }
  else if (event.type === 'workflow_step_start' && d.step) { icon = '▸'; text = `Step **${d.step}** started` }
  else if (event.type === 'forum_escalation') { icon = '▲'; text = String(d.message) }
  else if (event.type === 'agent_message') { icon = '›'; text = String(d.content || '') }
  else { text = Object.entries(d).filter(([, v]) => v != null).map(([k, v]) => `**${k}:** ${v}`).join(' · ') }

  return (
    <div className="sys-event">
      <span className="sys-icon">{icon}</span>
      <div className="markdown-body"><Markdown>{text}</Markdown></div>
    </div>
  )
}
