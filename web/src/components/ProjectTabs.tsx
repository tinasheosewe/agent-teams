import type { Project } from '../api'

interface Props {
  projects: Project[]
  activeId: string | null
  onSelect: (p: Project) => void
}

function statusColor(s: string): string {
  if (s === 'running') return 'var(--color-success)'
  if (s === 'completed') return 'var(--color-text-muted)'
  if (s === 'failed') return 'var(--color-danger)'
  if (s === 'paused') return 'var(--color-warning)'
  return 'var(--color-border)'
}

export default function ProjectTabs({ projects, activeId, onSelect }: Props) {
  if (projects.length === 0) return null

  return (
    <div className="project-tabs">
      {projects.map(p => (
        <button
          key={p.id}
          className={`project-tab ${p.id === activeId ? 'active' : ''}`}
          onClick={() => onSelect(p)}
        >
          <span className="project-tab-dot" style={{ background: statusColor(p.status) }} />
          <span className="project-tab-label">
            {p.prompt.slice(0, 24)}{p.prompt.length > 24 ? '…' : ''}
          </span>
        </button>
      ))}
    </div>
  )
}
