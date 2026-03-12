import { useRef, useEffect } from 'react'
import type { WsEvent } from '../hooks/useWebSocket'

function formatEventContent(event: WsEvent): string {
  const d = event.data
  switch (event.type) {
    case 'agent_message':
      return String(d.content || '')
    case 'team_mode_selected':
      return `Mode selected: ${d.mode} for task: ${d.task}`
    case 'team_round_start':
      return `Round ${d.round ?? ''} started (${d.team ?? ''})`
    case 'team_round_end':
      return `Round ${d.round ?? ''} ended — confidence: ${((d.confidence as number) * 100).toFixed(0)}%`
    case 'team_task_assigned':
      return `Tasks assigned: ${JSON.stringify(d.subtasks, null, 2)}`
    case 'decision_made':
      return `Decision: ${d.decision}\nRationale: ${d.rationale}`
    case 'forum_gate_result':
      return `Gate "${d.gate}": ${d.result} — ${d.notes}`
    case 'forum_escalation':
      return `⚠ ESCALATION: ${d.message}`
    case 'workflow_step_start':
      return d.step ? `Step "${d.step}" started (attempt ${d.attempt})` : String(d.message || '')
    case 'workflow_step_complete':
      return `Step "${d.step}" completed — gate "${d.gate}" passed`
    case 'workflow_complete':
      return `Workflow complete! Tokens: ${d.total_input_tokens} in / ${d.total_output_tokens} out`
    case 'artifact_created':
      return `Artifact created: ${d.artifact_type} by ${d.team}`
    case 'cost_update':
      return `Cost: $${(d.estimated_cost as number).toFixed(4)}`
    default:
      return JSON.stringify(d, null, 2)
  }
}

interface Props {
  events: WsEvent[]
}

export default function ConversationView({ events }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [events.length])

  if (events.length === 0) {
    return <div className="empty-state">Waiting for events...</div>
  }

  return (
    <div className="conversation-stream">
      {events.map((evt, i) => (
        <div key={i} className={`event-item ${evt.type}`}>
          <span className="event-type">{evt.type}</span>
          {evt.data.agent != null && (
            <span className="event-agent"> {String(evt.data.agent)}</span>
          )}
          {evt.data.phase != null && (
            <span className="event-type"> [{String(evt.data.phase)}]</span>
          )}
          <div className="event-content">{formatEventContent(evt)}</div>
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  )
}
