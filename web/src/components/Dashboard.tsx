import { useMemo } from 'react'
import type { WsEvent } from '../hooks/useWebSocket'

const TEAM_COLORS = [
  '#4d9eff', '#a78bfa', '#f0b429', '#34d058', '#f04848',
  '#22d3ee', '#f97316', '#ec4899', '#8b5cf6', '#10b981',
]

function hashColor(name: string): string {
  let h = 0
  for (let i = 0; i < name.length; i++) h = name.charCodeAt(i) + ((h << 5) - h)
  return TEAM_COLORS[Math.abs(h) % TEAM_COLORS.length]
}

interface StepInfo {
  name: string
  team: string
  gate: string
  status: 'pending' | 'in_progress' | 'completed' | 'failed'
  mode?: string
  attempt: number
  agents: string[]
}

interface Props {
  events: WsEvent[]
  selectedStep: string | null
  onSelectStep: (step: string | null) => void
}

export default function Dashboard({ events, selectedStep, onSelectStep }: Props) {
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
        if (info) info.status = 'completed'
      }
      if (evt.type === 'team_mode_selected' && evt.data.step) {
        const info = map.get(String(evt.data.step))
        if (info) info.mode = String(evt.data.mode)
      }
      // Track which agents have spoken per step
      if (evt.type === 'agent_message' && evt.data.agent) {
        // Find current in_progress step
        const current = [...ordered].reverse().find((s: StepInfo) => s.status === 'in_progress')
        if (current) {
          const agentName = String(evt.data.agent)
          if (!current.agents.includes(agentName)) {
            current.agents.push(agentName)
          }
        }
      }
    }
    return ordered
  }, [events])

  // Collect all unique agents across events
  const activeAgents = useMemo(() => {
    const agents = new Map<string, { team: string }>()
    for (const evt of events) {
      if (evt.data.agent && typeof evt.data.agent === 'string') {
        agents.set(evt.data.agent, { team: String(evt.data.team || '') })
      }
    }
    return agents
  }, [events])

  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <div className="sidebar-title">Workflow Pipeline</div>
      </div>

      <div className="pipeline">
        {steps.length === 0 ? (
          <p style={{ color: 'var(--text-muted)', fontSize: 13, padding: '8px 0' }}>
            No steps started yet.
          </p>
        ) : (
          steps.map((step) => {
            const color = hashColor(step.team)
            const isSelected = selectedStep === step.name
            return (
              <div
                key={step.name}
                className={`pipeline-step ${step.status === 'in_progress' ? 'active' : ''} ${isSelected ? 'selected' : ''}`}
                onClick={() => onSelectStep(isSelected ? null : step.name)}
              >
                <div className="step-row">
                  <div className={`step-icon ${step.status}`}>
                    {step.status === 'completed' ? '✓' : step.status === 'failed' ? '✕' : ''}
                  </div>
                  <div className="step-info">
                    <div className="step-name">{step.name}</div>
                    <div className="step-detail">
                      <span style={{ color }}>{step.team}</span>
                      {step.gate && (
                        <span className="step-gate-badge">{step.gate}</span>
                      )}
                      {step.attempt > 1 && (
                        <span style={{ color: 'var(--accent-yellow)', fontSize: 10 }}>
                          ×{step.attempt}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            )
          })
        )}
      </div>

      {/* Agent roster */}
      {activeAgents.size > 0 && (
        <div className="team-roster">
          <div className="team-roster-title">Active Agents ({activeAgents.size})</div>
          {Array.from(activeAgents.entries()).map(([name, { team }]) => (
            <div key={name} className="agent-row">
              <div
                className="agent-avatar"
                style={{ background: hashColor(team || name), width: 22, height: 22, fontSize: 9 }}
              >
                {name.split(/[_\s-]+/).map(w => w[0]?.toUpperCase() ?? '').join('').slice(0, 2)}
              </div>
              <span className="agent-name">{name}</span>
              {team && <span className="agent-role">{team}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
