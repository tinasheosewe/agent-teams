import { useState, useMemo } from 'react'
import Markdown from 'react-markdown'
import type { WsEvent } from '../hooks/useWebSocket'
import type { Decision, Artifact } from '../api'

/* ─── Helpers ─── */
const PALETTE = ['#818cf8', '#34d399', '#fbbf24', '#f87171', '#60a5fa', '#a78bfa', '#fb923c', '#2dd4bf']

function hashIdx(name: string): number {
  let h = 0
  for (let i = 0; i < name.length; i++) h = name.charCodeAt(i) + ((h << 5) - h)
  return Math.abs(h) % PALETTE.length
}

function confColor(c: number): string {
  if (c >= 0.8) return 'var(--green)'
  if (c >= 0.5) return 'var(--yellow)'
  return 'var(--red)'
}

function formatDuration(ms: number): string {
  if (ms < 1000) return '<1s'
  const s = Math.floor(ms / 1000)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const rem = s % 60
  return `${m}m ${rem}s`
}

/* ─── Compute step info from events ─── */
interface StepInfo {
  name: string
  team: string
  status: 'in_progress' | 'completed' | 'failed'
  mode: string | null
  rounds: number
  attempt: number
  fastTracked: boolean
  startTime: string | null
  endTime: string | null
  gateResult: string | null
  gateNotes: string | null
  tokenIn: number
  tokenOut: number
}

function computeStepInfo(events: WsEvent[], stepName: string): StepInfo {
  const info: StepInfo = {
    name: stepName,
    team: stepName,
    status: 'in_progress',
    mode: null,
    rounds: 0,
    attempt: 1,
    fastTracked: false,
    startTime: null,
    endTime: null,
    gateResult: null,
    gateNotes: null,
    tokenIn: 0,
    tokenOut: 0,
  }

  let inStep = false
  for (const evt of events) {
    if (evt.type === 'workflow_step_start' && String(evt.data.step) === stepName) {
      inStep = true
      info.team = String(evt.data.team || stepName)
      info.attempt = Number(evt.data.attempt ?? 1)
      info.startTime = evt.timestamp
      continue
    }
    if (evt.type === 'workflow_step_complete' && String(evt.data.step) === stepName) {
      info.status = 'completed'
      if (evt.data.fast_tracked) info.fastTracked = true
      info.endTime = evt.timestamp
      inStep = false
      continue
    }
    if (!inStep) continue

    if (evt.type === 'team_mode_selected') info.mode = String(evt.data.mode)
    if (evt.type === 'team_round_start') info.rounds++
    if (evt.type === 'forum_gate_result') {
      info.gateResult = String(evt.data.result ?? '')
      info.gateNotes = String(evt.data.notes ?? '')
    }
  }

  return info
}

function getStepDecisions(decisions: Decision[], stepTeam: string): Decision[] {
  return decisions.filter(d => d.team === stepTeam)
}

function getStepArtifacts(artifacts: Artifact[], stepTeam: string): Artifact[] {
  return artifacts.filter(a => a.team === stepTeam)
}

/* ─── Project summary ─── */
interface ProjectStats {
  totalSteps: number
  completedSteps: number
  totalDecisions: number
  totalArtifacts: number
  tokenIn: number
  tokenOut: number
  cost: number
  duration: string | null
}

function computeProjectStats(events: WsEvent[], decisions: Decision[], artifacts: Artifact[]): ProjectStats {
  let totalSteps = 0, completedSteps = 0, tokenIn = 0, tokenOut = 0, cost = 0
  const stepNames = new Set<string>()
  let firstTs: string | null = null
  let lastTs: string | null = null

  for (const evt of events) {
    if (evt.type === 'workflow_step_start' && evt.data.step) {
      stepNames.add(String(evt.data.step))
      if (!firstTs) firstTs = evt.timestamp
    }
    if (evt.type === 'workflow_step_complete') {
      completedSteps++
      lastTs = evt.timestamp
    }
    if (evt.type === 'cost_update') {
      tokenIn = Number(evt.data.input_tokens ?? 0)
      tokenOut = Number(evt.data.output_tokens ?? 0)
      cost = Number(evt.data.estimated_cost ?? 0)
    }
  }
  totalSteps = stepNames.size

  let duration: string | null = null
  if (firstTs && lastTs) {
    duration = formatDuration(new Date(lastTs).getTime() - new Date(firstTs).getTime())
  }

  return { totalSteps, completedSteps, totalDecisions: decisions.length, totalArtifacts: artifacts.length, tokenIn, tokenOut, cost, duration }
}

/* ─── Types ─── */
type ContextTab = 'decisions' | 'artifacts' | 'gate' | 'transcript'

interface Props {
  selectedNode: string | null
  events: WsEvent[]
  decisions: Decision[]
  artifacts: Artifact[]
  onVeto: (message: string) => void
  contextTab: ContextTab
  onChangeTab: (tab: ContextTab) => void
}

export default function StepDetailPanel({
  selectedNode, events, decisions, artifacts, onVeto, contextTab, onChangeTab,
}: Props) {
  const [expandedDecision, setExpandedDecision] = useState<string | null>(null)
  const [expandedArtifact, setExpandedArtifact] = useState<string | null>(null)
  const [transcriptFilter, setTranscriptFilter] = useState('')
  const [collapsedAgents, setCollapsedAgents] = useState<Set<string>>(new Set())

  // Step-level info
  const stepInfo = useMemo(
    () => selectedNode ? computeStepInfo(events, selectedNode) : null,
    [events, selectedNode],
  )

  const stepDecisions = useMemo(
    () => stepInfo ? getStepDecisions(decisions, stepInfo.team) : decisions,
    [decisions, stepInfo],
  )

  const stepArtifacts = useMemo(
    () => stepInfo ? getStepArtifacts(artifacts, stepInfo.team) : artifacts,
    [artifacts, stepInfo],
  )

  // Transcript: agent messages during this step
  const transcript = useMemo(() => {
    if (!selectedNode) return []
    const msgs: WsEvent[] = []
    let inStep = false
    for (const evt of events) {
      if (evt.type === 'workflow_step_start' && String(evt.data.step) === selectedNode) {
        inStep = true; continue
      }
      if (evt.type === 'workflow_step_complete' && String(evt.data.step) === selectedNode) {
        inStep = false; continue
      }
      if (inStep && evt.type === 'agent_message') msgs.push(evt)
    }
    return msgs
  }, [events, selectedNode])

  const projectStats = useMemo(
    () => !selectedNode ? computeProjectStats(events, decisions, artifacts) : null,
    [events, decisions, artifacts, selectedNode],
  )

  // No node selected → project summary
  if (!selectedNode) {
    return (
      <div className="context-panel">
        <div className="ctx-header">
          <h3 className="ctx-title">Project Overview</h3>
        </div>
        {projectStats && (
          <div className="ctx-summary-grid">
            <div className="ctx-stat">
              <span className="ctx-stat-value">{projectStats.completedSteps}/{projectStats.totalSteps}</span>
              <span className="ctx-stat-label">Steps</span>
            </div>
            <div className="ctx-stat">
              <span className="ctx-stat-value">{projectStats.totalDecisions}</span>
              <span className="ctx-stat-label">Decisions</span>
            </div>
            <div className="ctx-stat">
              <span className="ctx-stat-value">{projectStats.totalArtifacts}</span>
              <span className="ctx-stat-label">Artifacts</span>
            </div>
            <div className="ctx-stat">
              <span className="ctx-stat-value">${projectStats.cost.toFixed(4)}</span>
              <span className="ctx-stat-label">Cost</span>
            </div>
            {projectStats.duration && (
              <div className="ctx-stat">
                <span className="ctx-stat-value">{projectStats.duration}</span>
                <span className="ctx-stat-label">Duration</span>
              </div>
            )}
            <div className="ctx-stat">
              <span className="ctx-stat-value">{(projectStats.tokenIn + projectStats.tokenOut).toLocaleString()}</span>
              <span className="ctx-stat-label">Tokens</span>
            </div>
          </div>
        )}

        {/* All decisions */}
        {decisions.length > 0 && (
          <div className="ctx-section">
            <h4 className="ctx-section-title">All Decisions ({decisions.length})</h4>
            {decisions.map(d => (
              <DecisionRow key={d.id} decision={d} expanded={expandedDecision === d.id}
                onToggle={() => setExpandedDecision(expandedDecision === d.id ? null : d.id)}
                onVeto={onVeto} />
            ))}
          </div>
        )}

        {/* All artifacts */}
        {artifacts.length > 0 && (
          <div className="ctx-section">
            <h4 className="ctx-section-title">All Artifacts ({artifacts.length})</h4>
            {artifacts.map(a => (
              <ArtifactRow key={a.id} artifact={a} expanded={expandedArtifact === a.id}
                onToggle={() => setExpandedArtifact(expandedArtifact === a.id ? null : a.id)} />
            ))}
          </div>
        )}
      </div>
    )
  }

  if (!stepInfo) return null

  const color = PALETTE[hashIdx(stepInfo.team)]
  const duration = stepInfo.startTime && stepInfo.endTime
    ? formatDuration(new Date(stepInfo.endTime).getTime() - new Date(stepInfo.startTime).getTime())
    : stepInfo.startTime ? 'running...' : '—'

  const avgConf = stepDecisions.length > 0
    ? stepDecisions.reduce((sum, d) => sum + d.confidence, 0) / stepDecisions.length
    : null

  return (
    <div className="context-panel">
      {/* Header */}
      <div className="ctx-header">
        <div className="ctx-header-top">
          <div className="ctx-header-dot" style={{ background: color }} />
          <h3 className="ctx-title">{stepInfo.name}</h3>
          <span className={`status-badge ${stepInfo.status}`}>
            {stepInfo.status === 'in_progress' ? 'running' : stepInfo.status}
          </span>
        </div>
        <div className="ctx-header-meta">
          <span className="ctx-meta-item" style={{ color }}>{stepInfo.team}</span>
          {stepInfo.mode && <span className="mode-pill">{stepInfo.mode}</span>}
          <span className="ctx-meta-item">{stepInfo.rounds} round{stepInfo.rounds !== 1 ? 's' : ''}</span>
          <span className="ctx-meta-item">{duration}</span>
          {stepInfo.attempt > 1 && <span className="ctx-meta-attempt">attempt {stepInfo.attempt}</span>}
        </div>
        {avgConf !== null && (
          <div className="ctx-conf-bar-wrap">
            <span className="ctx-conf-label" style={{ color: confColor(avgConf) }}>
              {(avgConf * 100).toFixed(0)}%
            </span>
            <div className="ctx-conf-track">
              <div className="ctx-conf-fill" style={{ width: `${avgConf * 100}%`, background: confColor(avgConf) }} />
            </div>
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="ctx-tabs">
        {(['decisions', 'artifacts', 'gate', 'transcript'] as ContextTab[]).map(tab => (
          <button
            key={tab}
            className={`ctx-tab ${contextTab === tab ? 'active' : ''}`}
            onClick={() => onChangeTab(tab)}
          >
            {tab === 'decisions' ? `Decisions (${stepDecisions.length})`
              : tab === 'artifacts' ? `Artifacts (${stepArtifacts.length})`
              : tab === 'gate' ? 'Gate'
              : `Transcript (${transcript.length})`}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="ctx-body">
        {contextTab === 'decisions' && (
          stepDecisions.length === 0
            ? <div className="ctx-empty">No decisions in this step</div>
            : stepDecisions.map(d => (
              <DecisionRow key={d.id} decision={d} expanded={expandedDecision === d.id}
                onToggle={() => setExpandedDecision(expandedDecision === d.id ? null : d.id)}
                onVeto={onVeto} />
            ))
        )}

        {contextTab === 'artifacts' && (
          stepArtifacts.length === 0
            ? <div className="ctx-empty">No artifacts in this step</div>
            : stepArtifacts.map(a => (
              <ArtifactRow key={a.id} artifact={a} expanded={expandedArtifact === a.id}
                onToggle={() => setExpandedArtifact(expandedArtifact === a.id ? null : a.id)} />
            ))
        )}

        {contextTab === 'gate' && (
          <div className="ctx-gate-detail">
            {stepInfo.gateResult ? (
              <>
                <div className={`ctx-gate-result ${stepInfo.gateResult.toLowerCase().includes('approv') ? 'pass' : 'fail'}`}>
                  <span className="ctx-gate-icon">
                    {stepInfo.gateResult.toLowerCase().includes('approv') ? '✓' : '↩'}
                  </span>
                  <span className="ctx-gate-label">{stepInfo.gateResult}</span>
                </div>
                {stepInfo.gateNotes && (
                  <div className="ctx-gate-notes markdown-body">
                    <Markdown>{stepInfo.gateNotes}</Markdown>
                  </div>
                )}
              </>
            ) : (
              <div className="ctx-empty">Gate not yet evaluated</div>
            )}
          </div>
        )}

        {contextTab === 'transcript' && (
          transcript.length === 0
            ? <div className="ctx-empty">No messages in this step</div>
            : <TranscriptView
                messages={transcript}
                filter={transcriptFilter}
                onFilterChange={setTranscriptFilter}
                collapsedAgents={collapsedAgents}
                onToggleAgent={(agent) => setCollapsedAgents(prev => {
                  const next = new Set(prev)
                  next.has(agent) ? next.delete(agent) : next.add(agent)
                  return next
                })}
              />
        )}
      </div>
    </div>
  )
}

/* ─── Transcript View ─── */

interface TranscriptGroup {
  agent: string
  color: string
  messages: WsEvent[]
}

function groupByAgent(messages: WsEvent[]): TranscriptGroup[] {
  const groups: TranscriptGroup[] = []
  let current: TranscriptGroup | null = null

  for (const msg of messages) {
    const agent = String(msg.data.agent || 'Agent')
    if (current && current.agent === agent) {
      current.messages.push(msg)
    } else {
      current = { agent, color: PALETTE[hashIdx(agent)], messages: [msg] }
      groups.push(current)
    }
  }

  return groups
}

function TranscriptView({ messages, filter, onFilterChange, collapsedAgents, onToggleAgent }: {
  messages: WsEvent[]
  filter: string
  onFilterChange: (f: string) => void
  collapsedAgents: Set<string>
  onToggleAgent: (agent: string) => void
}) {
  const filtered = filter
    ? messages.filter(m => {
        const content = String(m.data.content || '').toLowerCase()
        const agent = String(m.data.agent || '').toLowerCase()
        const q = filter.toLowerCase()
        return content.includes(q) || agent.includes(q)
      })
    : messages

  const groups = groupByAgent(filtered)
  const agentNames = [...new Set(messages.map(m => String(m.data.agent || 'Agent')))]

  return (
    <div className="ctx-transcript">
      {/* Controls */}
      <div className="ctx-transcript-controls">
        <input
          className="ctx-transcript-search"
          type="text"
          placeholder="Filter messages…"
          value={filter}
          onChange={e => onFilterChange(e.target.value)}
        />
        <div className="ctx-transcript-agents">
          {agentNames.map(name => (
            <button
              key={name}
              className={`ctx-transcript-agent-btn ${collapsedAgents.has(name) ? 'muted' : ''}`}
              onClick={() => onToggleAgent(name)}
              title={collapsedAgents.has(name) ? `Show ${name}` : `Hide ${name}`}
            >
              <span className="ctx-transcript-agent-dot" style={{ background: PALETTE[hashIdx(name)] }} />
              {name.split(/[_\s-]+/).map(w => w[0]?.toUpperCase() ?? '').join('').slice(0, 2)}
            </button>
          ))}
        </div>
      </div>

      {/* Grouped messages */}
      {groups.map((group, gi) => {
        const hidden = collapsedAgents.has(group.agent)
        return (
          <div key={gi} className="ctx-transcript-group">
            <div
              className="ctx-transcript-group-header"
              onClick={() => onToggleAgent(group.agent)}
            >
              <span className={`chevron ${hidden ? '' : 'open'}`}>›</span>
              <span className="ctx-transcript-agent-dot" style={{ background: group.color }} />
              <span className="ctx-transcript-group-name">{group.agent}</span>
              <span className="ctx-transcript-group-count">{group.messages.length}</span>
            </div>
            {!hidden && group.messages.map((evt, mi) => {
              const name = String(evt.data.agent || 'Agent')
              return (
                <div key={mi} className="ctx-transcript-msg">
                  <div className="ctx-transcript-avatar" style={{ background: group.color }}>
                    {name.split(/[_\s-]+/).map(w => w[0]?.toUpperCase() ?? '').join('').slice(0, 2)}
                  </div>
                  <div className="ctx-transcript-body">
                    <div className="ctx-transcript-header">
                      <span className="ctx-transcript-name">{name}</span>
                      <span className="ctx-transcript-time">
                        {new Date(evt.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                      </span>
                    </div>
                    <div className="ctx-transcript-text markdown-body">
                      <Markdown>{String(evt.data.content || '')}</Markdown>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )
      })}

      {filtered.length === 0 && filter && (
        <div className="ctx-empty">No messages match "{filter}"</div>
      )}
    </div>
  )
}

/* ─── Reusable rows ─── */

function DecisionRow({ decision, expanded, onToggle, onVeto }: {
  decision: Decision; expanded: boolean; onToggle: () => void; onVeto: (msg: string) => void
}) {
  return (
    <div className="ctx-decision-row">
      <div className="ctx-decision-header" onClick={onToggle}>
        <span className={`chevron ${expanded ? 'open' : ''}`}>›</span>
        <span className="ctx-decision-topic">{decision.topic}</span>
        <span className="ctx-decision-conf" style={{ color: confColor(decision.confidence) }}>
          {(decision.confidence * 100).toFixed(0)}%
        </span>
        <span className={`badge ${decision.status === 'active' ? 'badge-success' : decision.status === 'draft' ? 'badge-info' : 'badge-neutral'}`}>
          {decision.status}
        </span>
      </div>
      <div className="ctx-decision-text markdown-body">
        <Markdown>{decision.decision}</Markdown>
      </div>
      {expanded && (
        <>
          {decision.rationale && (
            <div className="ctx-decision-rationale markdown-body">
              <Markdown>{decision.rationale}</Markdown>
            </div>
          )}
          <div className="ctx-decision-actions">
            <span className="ctx-decision-team">{decision.team}</span>
            <button
              className="btn btn-danger-outline btn-sm"
              onClick={(e) => { e.stopPropagation(); onVeto(`Flag decision: ${decision.topic}`) }}
              title="Flag this decision for human review — sends a veto to the orchestrator"
            >
              ⚑ Flag
            </button>
          </div>
        </>
      )}
    </div>
  )
}

function ArtifactRow({ artifact, expanded, onToggle }: {
  artifact: Artifact; expanded: boolean; onToggle: () => void
}) {
  return (
    <div className="ctx-artifact-row" onClick={onToggle}>
      <div className="ctx-artifact-header">
        <span className="ctx-artifact-name">{artifact.name}</span>
        <span className="ctx-artifact-meta">{artifact.type} · v{artifact.version}</span>
        <span className={`badge ${artifact.status === 'active' ? 'badge-success' : artifact.status === 'draft' ? 'badge-info' : 'badge-neutral'}`}>
          {artifact.status}
        </span>
        <span className={`chevron ${expanded ? 'open' : ''}`}>›</span>
      </div>
      {expanded && (
        <div className="ctx-artifact-content markdown-body">
          <Markdown>{artifact.content}</Markdown>
        </div>
      )}
    </div>
  )
}

export type { ContextTab }
