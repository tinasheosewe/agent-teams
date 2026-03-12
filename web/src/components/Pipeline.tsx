import { useMemo } from 'react'
import type { WsEvent } from '../hooks/useWebSocket'

const PALETTE = ['#818cf8', '#34d399', '#fbbf24', '#f87171', '#60a5fa', '#a78bfa', '#fb923c', '#2dd4bf']

function hashIdx(name: string): number {
  let h = 0
  for (let i = 0; i < name.length; i++) h = name.charCodeAt(i) + ((h << 5) - h)
  return Math.abs(h) % PALETTE.length
}

interface StepInfo {
  name: string
  team: string
  gate: string
  status: 'pending' | 'in_progress' | 'completed' | 'failed'
  attempt: number
  fastTracked: boolean
  agents: string[]
}

interface Props {
  events: WsEvent[]
  selectedStep: string | null
  onSelectStep: (step: string | null) => void
  collapsed: boolean
  onToggleCollapse: () => void
}

export default function Pipeline({ events, selectedStep, onSelectStep, collapsed, onToggleCollapse }: Props) {
  const steps = useMemo(() => {
    const map = new Map<string, StepInfo>()
    const ordered: StepInfo[] = []

    for (const evt of events) {
      if (evt.type === 'workflow_step_start' && evt.data.step) {
        const name = String(evt.data.step)
        if (!map.has(name)) {
          const info: StepInfo = {
            name,
            team: String(evt.data.team || name),
            gate: String(evt.data.gate || ''),
            status: 'in_progress',
            attempt: Number(evt.data.attempt ?? 1),
            fastTracked: false,
            agents: [],
          }
          map.set(name, info)
          ordered.push(info)
        } else {
          const info = map.get(name)!
          info.status = 'in_progress'
          info.attempt = Number(evt.data.attempt ?? info.attempt)
        }
      }
      if (evt.type === 'workflow_step_complete' && evt.data.step) {
        const info = map.get(String(evt.data.step))
        if (info) {
          info.status = 'completed'
          if (evt.data.fast_tracked) info.fastTracked = true
        }
      }
      if (evt.type === 'agent_message' && evt.data.agent) {
        const current = [...ordered].reverse().find(s => s.status === 'in_progress')
        if (current) {
          const a = String(evt.data.agent)
          if (!current.agents.includes(a)) current.agents.push(a)
        }
      }
    }
    return ordered
  }, [events])

  const stats = useMemo(() => {
    let tokens = 0, cost = 0
    for (const evt of events) {
      if (evt.type === 'cost_update') {
        tokens = Number(evt.data.total_input_tokens ?? 0) + Number(evt.data.total_output_tokens ?? 0)
        cost = Number(evt.data.estimated_cost ?? 0)
      }
    }
    return { tokens, cost }
  }, [events])

  return (
    <aside className={`pipeline ${collapsed ? 'collapsed' : ''}`}>
      <div className="pipeline-header">
        {!collapsed && <h3 className="pipeline-title">Pipeline</h3>}
        <button className="btn-icon" onClick={onToggleCollapse} title={collapsed ? 'Expand' : 'Collapse'}>
          {collapsed ? '▶' : '◀'}
        </button>
      </div>

      {!collapsed && (
        <>
          <div className="pipeline-steps">
            {steps.length === 0 && (
              <p className="pipeline-empty">Waiting for steps…</p>
            )}
            {steps.map((step, i) => {
              const color = PALETTE[hashIdx(step.team)]
              const isSelected = selectedStep === step.name
              const isLast = i === steps.length - 1

              return (
                <div key={step.name} className="step-row-wrap">
                  <div
                    className={`step ${step.status} ${isSelected ? 'selected' : ''} ${step.fastTracked ? 'fast-tracked' : ''}`}
                    onClick={() => onSelectStep(isSelected ? null : step.name)}
                  >
                    <div className="step-indicator">
                      <div className={`step-circle ${step.status}`}>
                        {step.status === 'completed' ? '✓' : step.status === 'failed' ? '✕' : step.fastTracked ? '⚡' : ''}
                      </div>
                      {!isLast && <div className={`step-line ${step.status === 'completed' ? 'done' : ''}`} />}
                    </div>
                    <div className="step-content">
                      <div className="step-name">{step.name}</div>
                      <div className="step-meta">
                        <span className="step-team-badge" style={{ color }}>{step.team}</span>
                        {step.attempt > 1 && <span className="step-attempt">×{step.attempt}</span>}
                        {step.fastTracked && <span className="step-fast">skipped</span>}
                      </div>
                      {step.agents.length > 0 && (
                        <div className="step-agents">
                          {step.agents.map(a => (
                            <span key={a} className="step-agent-chip">{a}</span>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>

          {stats.tokens > 0 && (
            <div className="pipeline-stats">
              <div className="stat-item">
                <span className="stat-label">Tokens</span>
                <span className="stat-value">{stats.tokens.toLocaleString()}</span>
              </div>
              <div className="stat-item">
                <span className="stat-label">Cost</span>
                <span className="stat-value">${stats.cost.toFixed(4)}</span>
              </div>
            </div>
          )}
        </>
      )}
    </aside>
  )
}
