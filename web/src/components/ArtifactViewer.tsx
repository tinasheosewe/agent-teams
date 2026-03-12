import { useState } from 'react'
import type { Artifact } from '../api'

interface Props {
  artifacts: Artifact[]
}

export default function ArtifactViewer({ artifacts }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null)

  if (artifacts.length === 0) {
    return <p style={{ color: 'var(--text-secondary)', fontSize: 13 }}>No artifacts yet.</p>
  }

  return (
    <div>
      {artifacts.map((a) => (
        <div key={a.id}>
          <div
            className="artifact-item"
            onClick={() => setExpanded(expanded === a.id ? null : a.id)}
          >
            <div className="artifact-name">{a.name}</div>
            <div className="artifact-type">
              {a.type} v{a.version}
              <span className={`badge ${a.status}`} style={{ marginLeft: 8 }}>
                {a.status}
              </span>
            </div>
          </div>
          {expanded === a.id && (
            <pre
              style={{
                padding: 12,
                background: 'var(--bg-primary)',
                borderRadius: 6,
                fontSize: 12,
                overflow: 'auto',
                maxHeight: 300,
                whiteSpace: 'pre-wrap',
                marginBottom: 8,
              }}
            >
              {a.content}
            </pre>
          )}
        </div>
      ))}
    </div>
  )
}
