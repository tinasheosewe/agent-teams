import type { WsEvent } from '../hooks/useWebSocket'

interface StepInfo {
  name: string
  gate: string
  status: 'pending' | 'in_progress' | 'completed' | 'failed'
}

interface Props {
  events: WsEvent[]
}

export default function Dashboard({ events }: Props) {
  // Extract workflow steps from events
  const steps: StepInfo[] = []
  const stepMap = new Map<string, StepInfo>()

  for (const evt of events) {
    if (evt.type === 'workflow_step_start' && evt.data.step) {
      const name = String(evt.data.step)
      if (!stepMap.has(name)) {
        const info: StepInfo = {
          name,
          gate: String(evt.data.gate || ''),
          status: 'in_progress',
        }
        stepMap.set(name, info)
        steps.push(info)
      } else {
        stepMap.get(name)!.status = 'in_progress'
      }
    }
    if (evt.type === 'workflow_step_complete' && evt.data.step) {
      const name = String(evt.data.step)
      const info = stepMap.get(name)
      if (info) info.status = 'completed'
    }
  }

  return (
    <div className="sidebar">
      <h2>Workflow</h2>
      {steps.length === 0 ? (
        <p style={{ color: 'var(--text-secondary)', fontSize: 13 }}>
          No steps started yet.
        </p>
      ) : (
        steps.map((step) => (
          <div key={step.name} className={`step ${step.status === 'in_progress' ? 'active' : ''}`}>
            <div className={`step-indicator ${step.status}`} />
            <div>
              <div className="step-name">{step.name}</div>
              <div className="step-gate">{step.gate}</div>
            </div>
          </div>
        ))
      )}
    </div>
  )
}
