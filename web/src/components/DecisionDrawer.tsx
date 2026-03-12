import { useState } from 'react'
import Markdown from 'react-markdown'
import type { Decision } from '../api'

interface Props {
  decisions: Decision[]
  onClose: () => void
}

function confColor(c: number): string {
  if (c >= 0.8) return 'var(--green)'
  if (c >= 0.5) return 'var(--yellow)'
  return 'var(--red)'
}

export default function DecisionDrawer({ decisions, onClose }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null)

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer" onClick={e => e.stopPropagation()}>
        <div className="drawer-header">
          <h3>Decisions ({decisions.length})</h3>
          <button className="btn-icon" onClick={onClose}>×</button>
        </div>
        <div className="drawer-body">
          {decisions.length === 0 ? (
            <div className="empty-state" style={{ padding: 48 }}>
              <div className="empty-state-icon">⇌</div>
              <div className="empty-state-title">No decisions yet</div>
            </div>
          ) : decisions.map(d => {
            const open = expanded === d.id
            return (
              <div key={d.id} className="decision-card">
                <div className="decision-card-header" onClick={() => setExpanded(open ? null : d.id)}>
                  <span className={`chevron ${open ? 'open' : ''}`}>›</span>
                  <span className="decision-topic">{d.topic}</span>
                  <span className={`badge ${d.status === 'active' ? 'badge-success' : d.status === 'draft' ? 'badge-info' : 'badge-neutral'}`}>
                    {d.status}
                  </span>
                </div>
                <div className="decision-text markdown-body">
                  <Markdown>{d.decision}</Markdown>
                </div>
                {open && d.rationale && (
                  <div className="decision-rationale markdown-body">
                    <Markdown>{d.rationale}</Markdown>
                  </div>
                )}
                <div className="decision-footer">
                  <span className="decision-team">{d.team}</span>
                  <div className="conf-meter">
                    <span className="conf-label" style={{ color: confColor(d.confidence) }}>
                      {(d.confidence * 100).toFixed(0)}%
                    </span>
                    <div className="conf-track">
                      <div
                        className="conf-bar"
                        style={{ width: `${d.confidence * 100}%`, background: confColor(d.confidence) }}
                      />
                    </div>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
