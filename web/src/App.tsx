import { useState, useEffect, useCallback } from 'react'
import { createProject, runProject, getProject, getDecisions, getArtifacts, listProjects, listConfigs, pauseProject, resumeProject, killProject } from './api'
import type { Project, Decision, Artifact, ConfigInfo } from './api'
import { useWebSocket } from './hooks/useWebSocket'
import Dashboard from './components/Dashboard'
import TeamActivityView from './components/ConversationView'
import DecisionLog from './components/DecisionLog'
import ArtifactViewer from './components/ArtifactViewer'
import UserInput from './components/UserInput'

type PanelTab = 'decisions' | 'artifacts'

export default function App() {
  const [prompt, setPrompt] = useState('')
  const [project, setProject] = useState<Project | null>(null)
  const [allProjects, setAllProjects] = useState<Project[]>([])
  const [decisions, setDecisions] = useState<Decision[]>([])
  const [artifacts, setArtifacts] = useState<Artifact[]>([])
  const [configs, setConfigs] = useState<ConfigInfo[]>([])
  const [selectedConfig, setSelectedConfig] = useState('')
  const [loading, setLoading] = useState(false)
  const [selectedStep, setSelectedStep] = useState<string | null>(null)
  const [panelTab, setPanelTab] = useState<PanelTab>('decisions')

  const { events, connected, send, clearEvents } = useWebSocket(project?.id ?? null)

  // Load configs and existing projects on mount
  useEffect(() => {
    listConfigs().then((c) => {
      setConfigs(c)
      if (c.length > 0) setSelectedConfig(c[0].path)
    }).catch(() => {})

    listProjects().then((ps) => {
      setAllProjects(ps)
      const active = ps.find((p) => p.status === 'running') ?? ps[ps.length - 1]
      if (active) {
        setProject(active)
        setPrompt(active.prompt)
      }
    }).catch(() => {})
  }, [])

  useEffect(() => {
    if (!project || project.status === 'completed' || project.status === 'failed') return
    const interval = setInterval(async () => {
      const updated = await getProject(project.id)
      setProject(updated)
      setAllProjects(prev => prev.map(p => p.id === updated.id ? updated : p))
      const d = await getDecisions(project.id)
      setDecisions(d)
      const a = await getArtifacts(project.id)
      setArtifacts(a)
    }, 3000)
    return () => clearInterval(interval)
  }, [project])

  const handleCreate = useCallback(async () => {
    if (!prompt.trim()) return
    setLoading(true)
    try {
      const p = await createProject(prompt, selectedConfig || undefined)
      setProject(p)
      setAllProjects(prev => [...prev, p])
      clearEvents()
      setDecisions([])
      setArtifacts([])
      const running = await runProject(p.id)
      setProject(running)
      setAllProjects(prev => prev.map(pp => pp.id === running.id ? running : pp))
    } finally {
      setLoading(false)
    }
  }, [prompt, selectedConfig, clearEvents])

  const handleSelectProject = useCallback(async (p: Project) => {
    setProject(p)
    setPrompt(p.prompt)
    clearEvents()
    setDecisions([])
    setArtifacts([])
    try {
      const d = await getDecisions(p.id)
      setDecisions(d)
      const a = await getArtifacts(p.id)
      setArtifacts(a)
    } catch { /* ignore */ }
  }, [clearEvents])

  const handlePause = useCallback(async () => {
    if (!project) return
    await pauseProject(project.id)
    const updated = await getProject(project.id)
    setProject(updated)
    setAllProjects(prev => prev.map(p => p.id === updated.id ? updated : p))
  }, [project])

  const handleResume = useCallback(async () => {
    if (!project) return
    await resumeProject(project.id)
    const updated = await getProject(project.id)
    setProject(updated)
    setAllProjects(prev => prev.map(p => p.id === updated.id ? updated : p))
  }, [project])

  const handleKill = useCallback(async () => {
    if (!project) return
    await killProject(project.id)
    const updated = await getProject(project.id)
    setProject(updated)
    setAllProjects(prev => prev.map(p => p.id === updated.id ? updated : p))
  }, [project])

  const handleUserInput = useCallback(
    (action: string, message: string) => {
      send(action, message)
    },
    [send],
  )

  const statusClass = project?.status === 'running' ? 'running'
    : project?.status === 'completed' ? 'completed'
    : project?.status === 'failed' ? 'failed'
    : project?.status === 'paused' ? 'running' : ''

  const currentConfig = configs.find(c => c.path === selectedConfig)

  return (
    <div className="app">
      {/* ─── Header ─── */}
      <div className="header">
        <div className="header-brand">
          <div className="header-logo">AA</div>
          <h1>AgentAgent</h1>
        </div>

        <div className="header-divider" />

        <div className="header-status">
          {project ? (
            <>
              <span className={`status-chip ${statusClass}`}>
                <span className={`status-dot ${project.status === 'running' ? 'pulse' : ''}`} />
                {project.status}
              </span>
              <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
                {project.config_name}
              </span>
              {/* Task controls */}
              <div className="task-controls">
                {project.status === 'running' && (
                  <button className="task-btn pause" onClick={handlePause} title="Pause">&#x23F8;</button>
                )}
                {project.status === 'paused' && (
                  <button className="task-btn play" onClick={handleResume} title="Resume">&#x25B6;</button>
                )}
                {(project.status === 'running' || project.status === 'paused') && (
                  <button className="task-btn kill" onClick={handleKill} title="Kill">&#x23F9;</button>
                )}
              </div>
            </>
          ) : (
            <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>No project</span>
          )}
        </div>

        <div className="header-meta">
          {project && (
            <>
              <span className="header-tokens">
                {project.total_input_tokens.toLocaleString()} in / {project.total_output_tokens.toLocaleString()} out
              </span>
              <span className="header-cost">
                ${project.estimated_cost.toFixed(4)}
              </span>
            </>
          )}
          <div
            className={`connection-dot ${connected ? 'connected' : ''}`}
            title={connected ? 'WebSocket connected' : 'Disconnected'}
          />
        </div>
      </div>

      {/* ─── Create Form ─── */}
      <div className="create-form">
        <select
          className="config-select"
          value={selectedConfig}
          onChange={(e) => setSelectedConfig(e.target.value)}
          disabled={loading}
        >
          {configs.map((c) => (
            <option key={c.path} value={c.path}>{c.name}</option>
          ))}
        </select>
        <input
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
          placeholder="Describe your project idea..."
          disabled={loading}
        />
        <button onClick={handleCreate} disabled={loading || !prompt.trim()}>
          {loading ? 'Starting...' : 'Launch Project'}
        </button>
      </div>

      {/* ─── Config Info ─── */}
      {currentConfig && (
        <div className="config-info-bar">
          <span className="config-desc">{currentConfig.description}</span>
          <span className="config-teams">{currentConfig.teams.join(' → ')}</span>
        </div>
      )}

      {/* ─── Project Tabs ─── */}
      {allProjects.length > 0 && (
        <div className="project-tabs">
          {allProjects.map((p) => (
            <button
              key={p.id}
              className={`project-tab ${p.id === project?.id ? 'active' : ''}`}
              onClick={() => handleSelectProject(p)}
            >
              <span className={`project-tab-dot ${p.status}`} />
              <span className="project-tab-label">{p.prompt.slice(0, 30)}{p.prompt.length > 30 ? '…' : ''}</span>
            </button>
          ))}
        </div>
      )}

      {/* ─── Main Layout ─── */}
      <div className="main">
        {/* Left — Pipeline */}
        <Dashboard
          events={events}
          selectedStep={selectedStep}
          onSelectStep={setSelectedStep}
        />

        {/* Center — Team Activity */}
        <div className="center-panel">
          <TeamActivityView events={events} selectedStep={selectedStep} />
          <UserInput onSend={handleUserInput} disabled={!project} />
        </div>

        {/* Right — Tabbed Panel */}
        <div className="panel">
          <div className="panel-tabs">
            <button
              className={`panel-tab ${panelTab === 'decisions' ? 'active' : ''}`}
              onClick={() => setPanelTab('decisions')}
            >
              Decisions
              <span className="panel-tab-count">{decisions.length}</span>
            </button>
            <button
              className={`panel-tab ${panelTab === 'artifacts' ? 'active' : ''}`}
              onClick={() => setPanelTab('artifacts')}
            >
              Artifacts
              <span className="panel-tab-count">{artifacts.length}</span>
            </button>
          </div>
          <div className="panel-content">
            {panelTab === 'decisions' && <DecisionLog decisions={decisions} />}
            {panelTab === 'artifacts' && <ArtifactViewer artifacts={artifacts} />}
          </div>
        </div>
      </div>
    </div>
  )
}
