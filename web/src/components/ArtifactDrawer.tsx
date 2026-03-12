import { useState } from 'react'
import Markdown from 'react-markdown'
import type { Artifact } from '../api'

interface Props {
  artifacts: Artifact[]
  onClose: () => void
}

function artIcon(type: string): string {
  const t = type.toLowerCase()
  if (t.includes('code') || t.includes('implementation')) return '{ }'
  if (t.includes('doc') || t.includes('spec') || t.includes('readme')) return '¶'
  if (t.includes('design') || t.includes('ui') || t.includes('ux')) return '◑'
  if (t.includes('test')) return '⊘'
  if (t.includes('config') || t.includes('infra')) return '⚙'
  if (t.includes('plan') || t.includes('architecture')) return '△'
  return '□'
}

export default function ArtifactDrawer({ artifacts, onClose }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null)

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer" onClick={e => e.stopPropagation()}>
        <div className="drawer-header">
          <h3>Artifacts ({artifacts.length})</h3>
          <button className="btn-icon" onClick={onClose}>×</button>
        </div>
        <div className="drawer-body">
          {artifacts.length === 0 ? (
            <div className="empty-state" style={{ padding: 48 }}>
              <div className="empty-state-icon">◻</div>
              <div className="empty-state-title">No artifacts yet</div>
            </div>
          ) : artifacts.map(a => {
            const open = expanded === a.id
            return (
              <div key={a.id} className="artifact-card" onClick={() => setExpanded(open ? null : a.id)}>
                <div className="artifact-card-header">
                  <span className="artifact-icon">{artIcon(a.type)}</span>
                  <div className="artifact-info">
                    <div className="artifact-name">{a.name}</div>
                    <div className="artifact-meta">
                      <span>{a.type}</span> · <span>v{a.version}</span>
                      <span className={`badge ${a.status === 'active' ? 'badge-success' : a.status === 'draft' ? 'badge-info' : 'badge-neutral'}`}>
                        {a.status}
                      </span>
                    </div>
                  </div>
                  <span className={`chevron ${open ? 'open' : ''}`}>›</span>
                </div>
                {open && (
                  <div className="artifact-content markdown-body" onClick={e => e.stopPropagation()}>
                    <Markdown>{a.content}</Markdown>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
