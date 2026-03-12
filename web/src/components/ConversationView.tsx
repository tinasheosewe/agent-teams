import { useRef, useEffect, useCallback, useState, useMemo } from 'react'
import Markdown from 'react-markdown'
import type { WsEvent } from '../hooks/useWebSocket'

/* ─── Colour helpers ─── */
const TEAM_COLORS = [
  '#4d9eff', '#a78bfa', '#f0b429', '#34d058', '#f04848',
  '#22d3ee', '#f97316', '#ec4899', '#8b5cf6', '#10b981',
]

function hashColor(name: string): string {
  let h = 0
  for (let i = 0; i < name.length; i++) h = name.charCodeAt(i) + ((h << 5) - h)
  return TEAM_COLORS[Math.abs(h) % TEAM_COLORS.length]
}

function initials(name: string): string {
  return name.split(/[_\s-]+/).map(w => w[0]?.toUpperCase() ?? '').join('').slice(0, 2)
}

function extractTaskSummary(task: string): string {
  // Pull just the user request line and the team purpose, skip upstream context
  const requestMatch = task.match(/User's original request:\s*(.+)/)
  const purposeMatch = task.match(/Your team's purpose:\s*(\S+)/)
  const produceMatch = task.match(/Produce:\s*(.+)/)
  const parts: string[] = []
  if (requestMatch) parts.push(`"${requestMatch[1].trim()}"`)
  if (purposeMatch) parts.push(`→ ${purposeMatch[1]}`)
  if (produceMatch) parts.push(`→ produce ${produceMatch[1].trim()}`)
  return parts.length > 0 ? parts.join(' ') : task.slice(0, 120)
}

function modeClass(mode: string): string {
  const m = mode.toLowerCase()
  if (m.includes('generat')) return 'generative'
  if (m.includes('evaluat')) return 'evaluative'
  if (m.includes('execut')) return 'execution'
  if (m.includes('decis')) return 'decision'
  return 'generative'
}

/* ─── Group events into team sections ─── */
interface TeamSection {
  id: string
  stepName: string
  teamName: string
  attempt: number
  status: 'in_progress' | 'completed' | 'failed'
  mode?: string
  task?: string
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

    if (current) {
      current.events.push(evt)
    } else {
      trailing.push(evt)
    }
  }

  return { sections, trailing }
}

/* ─── Sub-group events inside a section into rounds ─── */
interface RoundGroup {
  round: number
  confidence?: number
  events: WsEvent[]
}

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
    if (current) {
      current.events.push(evt)
    }
  }

  return rounds
}

/* ─── Component ─── */
interface Props {
  events: WsEvent[]
  selectedStep: string | null
}

export default function TeamActivityView({ events, selectedStep }: Props) {
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
    if (isNearBottom) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [events.length, isNearBottom])

  const { sections, trailing } = useMemo(() => buildTeamSections(events), [events])

  // Filter to selected step if set
  const visibleSections = selectedStep
    ? sections.filter(s => s.stepName === selectedStep)
    : sections

  const toggleSection = (id: string) => {
    setCollapsed(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const toggleRound = (key: string) => {
    setCollapsedRounds(prev => {
      const next = new Set(prev)
      next.has(key) ? next.delete(key) : next.add(key)
      return next
    })
  }

  if (events.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon">&#x1F680;</div>
        <div className="empty-state-text">Launch a project to begin</div>
      </div>
    )
  }

  return (
    <div className="activity-stream" ref={containerRef} onScroll={handleScroll}>
      {/* Show trailing events that came before any workflow_step_start */}
      {!selectedStep && trailing.filter(e => e.type !== 'cost_update').map((evt, i) => (
        <SystemEventRow key={`t-${i}`} event={evt} />
      ))}

      {visibleSections.map((section) => {
        const isOpen = !collapsed.has(section.id)
        const color = hashColor(section.teamName)
        const rounds = buildRounds(section.events)

        return (
          <div className="team-section" key={section.id}>
            {/* Header */}
            <div className="team-section-header" onClick={() => toggleSection(section.id)}>
              <div className="team-color-stripe" style={{ background: color }} />
              <div className="team-section-info">
                <div className="team-section-name">{section.stepName}</div>
                <div className="team-section-meta">
                  <span>{section.teamName}</span>
                  {section.attempt > 1 && <span>attempt {section.attempt}</span>}
                  <span className={`badge ${section.status === 'completed' ? 'active' : section.status === 'failed' ? '' : 'draft'}`}>
                    {section.status === 'in_progress' ? 'running' : section.status}
                  </span>
                </div>
              </div>
              {section.mode && (
                <span className={`mode-badge ${modeClass(section.mode)}`}>
                  {section.mode}
                </span>
              )}
              <span className={`team-section-chevron ${isOpen ? 'open' : ''}`}>&#x25B6;</span>
            </div>

            {/* Body */}
            {isOpen && (
              <div className="team-section-body">
                {/* Mode banner */}
                {section.mode && section.task && (
                  <div className="mode-banner">
                    <span className={`mode-badge ${modeClass(section.mode)}`}>{section.mode}</span>
                    <span className="mode-task">{extractTaskSummary(section.task)}</span>
                  </div>
                )}

                {/* Rounds */}
                {rounds.map((round) => {
                  const roundKey = `${section.id}-r${round.round}`
                  const roundOpen = !collapsedRounds.has(roundKey)
                  return (
                    <div className="round-group" key={roundKey}>
                      <div className="round-header" onClick={() => toggleRound(roundKey)}>
                        <span className="round-label">
                          {roundOpen ? '▾' : '▸'} Round {round.round}
                        </span>
                        {round.confidence != null && (
                          <span className="round-confidence" style={{
                            color: round.confidence >= 0.8 ? 'var(--accent-green)' : round.confidence >= 0.5 ? 'var(--accent-yellow)' : 'var(--accent-red)'
                          }}>
                            {(round.confidence * 100).toFixed(0)}%
                          </span>
                        )}
                      </div>
                      {roundOpen && round.events.map((evt, j) => (
                        <EventRow key={j} event={evt} teamColor={color} />
                      ))}
                    </div>
                  )
                })}

                {/* Events not in any round (gate results, artifacts, etc.) */}
                {section.events
                  .filter(e =>
                    !['workflow_step_start', 'workflow_step_complete', 'team_mode_selected',
                      'team_round_start', 'team_round_end', 'cost_update'].includes(e.type) &&
                    !rounds.some(r => r.events.includes(e))
                  )
                  .map((evt, j) => (
                    <EventRow key={`extra-${j}`} event={evt} teamColor={color} />
                  ))}

                {/* Gate result if step completed */}
                {section.events.filter(e => e.type === 'forum_gate_result').map((evt, j) => (
                  <GateResultCard key={`gate-${j}`} event={evt} />
                ))}
              </div>
            )}
          </div>
        )
      })}

      {/* Workflow complete */}
      {events.some(e => e.type === 'workflow_complete') && (
        <div className="workflow-complete-banner">
          <h3>Workflow Complete</h3>
          {events.filter(e => e.type === 'workflow_complete').map((e, i) => (
            <p key={i}>
              {String(e.data.total_input_tokens)} input tokens &middot; {String(e.data.total_output_tokens)} output tokens
            </p>
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
    const agentName = String(d.agent || 'Agent')
    return (
      <div className="agent-bubble">
        <div className="bubble-avatar" style={{ background: teamColor }}>
          {initials(agentName)}
        </div>
        <div className="bubble-content">
          <div className="bubble-header">
            <span className="bubble-agent-name">{agentName}</span>
            <span className="bubble-time">{new Date(event.timestamp).toLocaleTimeString()}</span>
          </div>
          <div className="bubble-text markdown-body">
            <Markdown>{String(d.content || '')}</Markdown>
          </div>
        </div>
      </div>
    )
  }

  if (event.type === 'team_mode_selected') {
    return (
      <div className="system-event">
        <span className="system-event-icon">&#x1F3AF;</span>
        <span className="system-event-text">
          Mode: <strong>{String(d.mode)}</strong>
        </span>
      </div>
    )
  }

  if (event.type === 'team_task_assigned') {
    return (
      <div className="system-event">
        <span className="system-event-icon">&#x1F4CB;</span>
        <div className="system-event-text markdown-body">
          <Markdown>{`**Tasks assigned:**\n\`\`\`json\n${JSON.stringify(d.subtasks, null, 2)}\n\`\`\``}</Markdown>
        </div>
      </div>
    )
  }

  if (event.type === 'decision_made') {
    return (
      <div className="system-event">
        <span className="system-event-icon">&#x2705;</span>
        <div className="system-event-text markdown-body">
          <Markdown>{`**Decision:** ${d.decision}`}</Markdown>
        </div>
      </div>
    )
  }

  if (event.type === 'artifact_created') {
    return (
      <div className="system-event">
        <span className="system-event-icon">&#x1F4C4;</span>
        <span className="system-event-text">
          Artifact <strong>{String(d.artifact_type)}</strong> created
        </span>
      </div>
    )
  }

  if (event.type === 'forum_escalation') {
    return (
      <div className="escalation-banner">
        &#x26A0;&#xFE0F; {String(d.message)}
      </div>
    )
  }

  if (event.type === 'agent_tool_call') {
    return (
      <div className="system-event">
        <span className="system-event-icon">&#x1F527;</span>
        <span className="system-event-text">
          <strong>{String(d.agent || '')}</strong> called <strong>{String(d.tool || '')}</strong>
        </span>
      </div>
    )
  }

  // Fallback
  return (
    <div className="system-event">
      <span className="system-event-icon">&#x2022;</span>
      <div className="system-event-text markdown-body">
        <Markdown>{'```json\n' + JSON.stringify(d, null, 2) + '\n```'}</Markdown>
      </div>
    </div>
  )
}

function GateResultCard({ event }: { event: WsEvent }) {
  const d = event.data
  const passed = String(d.result).toLowerCase().includes('pass')
  return (
    <div className={`gate-card ${passed ? 'passed' : 'failed'}`}>
      <div className="gate-card-header">
        <span className="gate-card-title">Gate: {String(d.gate)}</span>
        <span className={`gate-card-result ${passed ? 'passed' : 'failed'}`}>
          {String(d.result)}
        </span>
      </div>
      {d.notes ? <div className="gate-card-notes">{String(d.notes)}</div> : null}
    </div>
  )
}

function SystemEventRow({ event }: { event: WsEvent }) {
  const d = event.data
  if (event.type === 'workflow_complete') return null

  let icon = '•'
  let text = ''
  if (event.type === 'workflow_step_start' && d.message) { icon = '🚀'; text = String(d.message) }
  else if (event.type === 'workflow_step_start' && d.step) { icon = '🚀'; text = `Step **${d.step}** started` }
  else if (event.type === 'forum_escalation') { icon = '⚠️'; text = String(d.message) }
  else if (event.type === 'agent_message') { icon = '💬'; text = String(d.content || '') }
  else { text = Object.entries(d).filter(([,v]) => v != null).map(([k,v]) => `**${k}:** ${v}`).join(' · ') }

  return (
    <div className="system-event">
      <span className="system-event-icon">{icon}</span>
      <div className="system-event-text markdown-body">
        <Markdown>{text}</Markdown>
      </div>
    </div>
  )
}
