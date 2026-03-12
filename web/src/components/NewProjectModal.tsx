import { useState } from 'react'
import type { ConfigInfo } from '../api'

interface Props {
  configs: ConfigInfo[]
  selectedConfig: string
  onChangeConfig: (path: string) => void
  onCreate: (prompt: string) => void
  onClose: () => void
  loading: boolean
}

export default function NewProjectModal({
  configs, selectedConfig, onChangeConfig, onCreate, onClose, loading,
}: Props) {
  const [prompt, setPrompt] = useState('')
  const current = configs.find(c => c.path === selectedConfig)

  const handleSubmit = () => {
    if (prompt.trim()) onCreate(prompt.trim())
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h3>New Project</h3>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          <label className="form-label">Configuration</label>
          <select
            className="form-select"
            value={selectedConfig}
            onChange={e => onChangeConfig(e.target.value)}
          >
            {configs.map(c => (
              <option key={c.path} value={c.path}>{c.name}</option>
            ))}
          </select>
          {current && (
            <p className="form-hint">
              {current.description} — {current.teams.length} team{current.teams.length !== 1 ? 's' : ''}
            </p>
          )}

          <label className="form-label" style={{ marginTop: 16 }}>Project Prompt</label>
          <textarea
            className="form-textarea"
            value={prompt}
            onChange={e => setPrompt(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && e.metaKey) handleSubmit() }}
            placeholder="Describe what you want to build…"
            rows={4}
            autoFocus
          />
          <p className="form-hint">Press ⌘Enter to launch</p>
        </div>
        <div className="modal-footer">
          <button className="btn btn-ghost btn-sm" onClick={onClose}>Cancel</button>
          <button
            className="btn btn-primary btn-sm"
            onClick={handleSubmit}
            disabled={loading || !prompt.trim()}
          >
            {loading ? 'Launching…' : 'Launch Project'}
          </button>
        </div>
      </div>
    </div>
  )
}
