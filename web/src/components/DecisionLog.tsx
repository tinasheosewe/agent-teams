import { useState } from 'react'
import Markdown from 'react-markdown'
import type { Decision } from '../api'

interface Props {
  decisions: Decision[]
}

function confidenceColor(c: number): string {
  if (c >= 0.8) return 'var(--accent-green)'
  if (c >= 0.5) return 'var(--accent-yellow)'
  return 'var(--accent-red)'
}

export default function DecisionLog({ decisions }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null)

  if (decisions.length === 0) {
    return (
      <div className="empty-state" style={{ height: 'auto', padding: 24 }}>
        <div style={{ fontSize: 32, opacity: 0.3 }}>&#x2696;</div>
        <div className="empty-state-text">No decisions yet</div>
      </div>
    )
  }

  return (
    <div>
      {decisions.map((d) => {
        const isOpen = expanded === d.id
        return (
          <div key={d.id} className="decision-card">
            <div
              className="decision-card-header"
              onClick={() => setExpanded(isOpen ? null : d.id)}
            >
              <span className={`decision-card-toggle ${isOpen ? 'open' : ''}`}>&#x25B6;</span>
              <span className="decision-card-topic">{d.topic}</span>
              <span className={`badge ${d.status}`}>{d.status}</span>
            </div>

            <div className="decision-card-text markdown-body">
              <Markdown>{d.decision}</Markdown>
            </div>

            {isOpen && d.rationale && (
              <div className="decision-card-rationale markdown-body">
                <Markdown>{d.rationale}</Markdown>
              </div>
            )}

            <div className="decision-card-footer">
              <span className="decision-team-label">{d.team}</span>
              <div className="confidence-meter">
                <span className="confidence-label" style={{ color: confidenceColor(d.confidence) }}>
                  {(d.confidence * 100).toFixed(0)}%
                </span>
                <div className="confidence-track">
                  <div
                    className="confidence-bar"
                    style={{
                      width: `${d.confidence * 100}%`,
                      background: confidenceColor(d.confidence),
                    }}
                  />
                </div>
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
