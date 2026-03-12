import { useState } from 'react'
import Markdown from 'react-markdown'
import type { Artifact } from '../api'

interface Props {
  artifacts: Artifact[]
}

function artifactIcon(type: string): string {
  const t = type.toLowerCase()
  if (t.includes('code') || t.includes('implementation')) return '\u{1F4BB}'
  if (t.includes('doc') || t.includes('spec') || t.includes('readme')) return '\u{1F4DD}'
  if (t.includes('design') || t.includes('ui') || t.includes('ux')) return '\u{1F3A8}'
  if (t.includes('test')) return '\u{1F9EA}'
  if (t.includes('config') || t.includes('infra')) return '\u{2699}'
  if (t.includes('plan') || t.includes('architecture')) return '\u{1F3D7}'
  return '\u{1F4C4}'
}

export default function ArtifactViewer({ artifacts }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null)

  if (artifacts.length === 0) {
    return (
      <div className="empty-state" style={{ height: 'auto', padding: 24 }}>
        <div style={{ fontSize: 32, opacity: 0.3 }}>&#x1F4E6;</div>
        <div className="empty-state-text">No artifacts yet</div>
      </div>
    )
  }

  return (
    <div>
      {artifacts.map((a) => {
        const isOpen = expanded === a.id
        return (
          <div key={a.id} className="artifact-card" onClick={() => setExpanded(isOpen ? null : a.id)}>
            <div className="artifact-card-header">
              <span className="artifact-card-icon">{artifactIcon(a.type)}</span>
              <div className="artifact-card-info">
                <div className="artifact-card-name">{a.name}</div>
                <div className="artifact-card-meta">
                  <span>{a.type}</span>
                  <span>v{a.version}</span>
                  <span className={`badge ${a.status}`}>{a.status}</span>
                </div>
              </div>
              <span className={`artifact-card-toggle ${isOpen ? 'open' : ''}`}>&#x25B6;</span>
            </div>
            {isOpen && (
              <div className="artifact-card-content markdown-body" onClick={(e) => e.stopPropagation()}>
                <Markdown>{a.content}</Markdown>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
