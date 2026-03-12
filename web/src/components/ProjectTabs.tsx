import type { Project } from '../api'

interface Props {
  projects: Project[]
  activeId: string | null
  onSelect: (p: Project) => void
}

function statusColor(s: string): string {
  if (s === 'running') return 'var(--green)'
  if (s === 'completed') return 'var(--text-3)'
  if (s === 'failed') return 'var(--red)'
  if (s === 'paused') return 'var(--yellow)'
  return 'var(--border)'
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
            {p.prompt.slice(0, 18)}{p.prompt.length > 18 ? '…' : ''}
          </span>
        </button>
      ))}
    </div>
  )
}
