import type { Project } from '../api'

interface Props {
  projects: Project[]
  onSelect: (p: Project) => void
  onNew: () => void
}

function statusLabel(s: string) {
  if (s === 'running') return { text: 'Running', cls: 'badge-success' }
  if (s === 'completed') return { text: 'Completed', cls: 'badge-neutral' }
  if (s === 'failed') return { text: 'Failed', cls: 'badge-danger' }
  if (s === 'paused') return { text: 'Paused', cls: 'badge-warning' }
  return { text: s, cls: 'badge-neutral' }
}

export default function ProjectList({ projects, onSelect, onNew }: Props) {
  return (
    <div className="project-list-view">
      <div className="project-list-header">
        <div>
          <h2>Projects</h2>
          <p className="project-list-subtitle">
            {projects.length} project{projects.length !== 1 ? 's' : ''}
          </p>
        </div>
        <button className="btn btn-primary btn-sm" onClick={onNew}>+ New Project</button>
      </div>

      {projects.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">📂</div>
          <div className="empty-state-title">No projects yet</div>
          <p className="empty-state-text">Create your first project to get started.</p>
          <button className="btn btn-primary btn-sm" onClick={onNew}>+ New Project</button>
        </div>
      ) : (
        <div className="project-grid">
          {projects.map(p => {
            const st = statusLabel(p.status)
            return (
              <div key={p.id} className="project-card" onClick={() => onSelect(p)}>
                <div className="project-card-top">
                  <span className={`badge ${st.cls}`}>{st.text}</span>
                  <span className="project-card-config">{p.config_name}</span>
                </div>
                <div className="project-card-prompt">{p.prompt}</div>
                <div className="project-card-stats">
                  <span>{p.total_input_tokens.toLocaleString()} in</span>
                  <span>{p.total_output_tokens.toLocaleString()} out</span>
                  <span>${p.estimated_cost.toFixed(4)}</span>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
