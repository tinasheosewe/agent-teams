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
  if (decisions.length === 0) {
    return <p style={{ color: 'var(--text-secondary)', fontSize: 13 }}>No decisions yet.</p>
  }

  return (
    <div>
      {decisions.map((d) => (
        <div key={d.id} className="decision-item">
          <div className="decision-topic">
            {d.topic}
            <span className={`badge ${d.status}`} style={{ marginLeft: 8 }}>
              {d.status}
            </span>
          </div>
          <div className="decision-text">{d.decision}</div>
          <div className="decision-meta">
            <span>{d.team}</span>
            <span>
              {(d.confidence * 100).toFixed(0)}%
              <span className="confidence-bar">
                <span
                  className="confidence-fill"
                  style={{
                    width: `${d.confidence * 100}%`,
                    background: confidenceColor(d.confidence),
                  }}
                />
              </span>
            </span>
          </div>
        </div>
      ))}
    </div>
  )
}
