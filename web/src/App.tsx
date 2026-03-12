import { useState, useEffect, useCallback } from 'react'
import { createProject, runProject, getProject, getDecisions, getArtifacts, listProjects, listConfigs, pauseProject, resumeProject, killProject } from './api'
import type { Project, Decision, Artifact, ConfigInfo } from './api'
import { useWebSocket } from './hooks/useWebSocket'
import ProjectTabs from './components/ProjectTabs'
import ProjectList from './components/ProjectList'
import Pipeline from './components/Pipeline'
import ActivityStream from './components/ActivityStream'
import CommandPalette from './components/CommandPalette'
import NewProjectModal from './components/NewProjectModal'
import DecisionDrawer from './components/DecisionDrawer'
import ArtifactDrawer from './components/ArtifactDrawer'
import UserInput from './components/UserInput'

type View = 'projects' | 'detail'

export default function App() {
  const [view, setView] = useState<View>('projects')
  const [project, setProject] = useState<Project | null>(null)
  const [allProjects, setAllProjects] = useState<Project[]>([])
  const [decisions, setDecisions] = useState<Decision[]>([])
  const [artifacts, setArtifacts] = useState<Artifact[]>([])
  const [configs, setConfigs] = useState<ConfigInfo[]>([])
  const [selectedConfig, setSelectedConfig] = useState('')
  const [loading, setLoading] = useState(false)
  const [selectedStep, setSelectedStep] = useState<string | null>(null)
  const [pipelineCollapsed, setPipelineCollapsed] = useState(false)
  const [showPalette, setShowPalette] = useState(false)
  const [showNewProject, setShowNewProject] = useState(false)
  const [showDecisions, setShowDecisions] = useState(false)
  const [showArtifacts, setShowArtifacts] = useState(false)

  const { events, connected, send, clearEvents } = useWebSocket(project?.id ?? null)

  // Load on mount
  useEffect(() => {
    listConfigs().then(c => {
      setConfigs(c)
      if (c.length > 0) setSelectedConfig(c[0].path)
    }).catch(() => {})

    listProjects().then(ps => {
      setAllProjects(ps)
      const active = ps.find(p => p.status === 'running') ?? ps[ps.length - 1]
      if (active) {
        setProject(active)
        setView('detail')
      }
    }).catch(() => {})
  }, [])

  // Poll running project
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

  // Cmd+K shortcut
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setShowPalette(v => !v)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  const handleSelectProject = useCallback(async (p: Project) => {
    setProject(p)
    setView('detail')
    clearEvents()
    setDecisions([])
    setArtifacts([])
    setSelectedStep(null)
    try {
      const d = await getDecisions(p.id)
      setDecisions(d)
      const a = await getArtifacts(p.id)
      setArtifacts(a)
    } catch { /* ignore */ }
  }, [clearEvents])

  const handleCreate = useCallback(async (prompt: string) => {
    setLoading(true)
    try {
      const p = await createProject(prompt, selectedConfig || undefined)
      setProject(p)
      setAllProjects(prev => [...prev, p])
      clearEvents()
      setDecisions([])
      setArtifacts([])
      setView('detail')
      setShowNewProject(false)
      const running = await runProject(p.id)
      setProject(running)
      setAllProjects(prev => prev.map(pp => pp.id === running.id ? running : pp))
    } finally {
      setLoading(false)
    }
  }, [selectedConfig, clearEvents])

  const handlePause = useCallback(async () => {
    if (!project) return
    await pauseProject(project.id)
    const u = await getProject(project.id)
    setProject(u)
    setAllProjects(prev => prev.map(p => p.id === u.id ? u : p))
  }, [project])

  const handleResume = useCallback(async () => {
    if (!project) return
    await resumeProject(project.id)
    const u = await getProject(project.id)
    setProject(u)
    setAllProjects(prev => prev.map(p => p.id === u.id ? u : p))
  }, [project])

  const handleKill = useCallback(async () => {
    if (!project) return
    await killProject(project.id)
    const u = await getProject(project.id)
    setProject(u)
    setAllProjects(prev => prev.map(p => p.id === u.id ? u : p))
  }, [project])

  const handleSend = useCallback((action: string, message: string) => {
    send(action, message)
  }, [send])

  return (
    <div className="app">
      {/* ─── Navbar ─── */}
      <nav className="navbar">
        <div className="navbar-left">
          <div className="navbar-brand" onClick={() => setView('projects')} style={{ cursor: 'pointer' }}>
            <div className="navbar-logo">AA</div>
            <span className="navbar-title">AgentAgent</span>
          </div>
          <div className="navbar-divider" />
          <ProjectTabs projects={allProjects} activeId={project?.id ?? null} onSelect={handleSelectProject} />
        </div>
        <div className="navbar-right">
          <select
            className="config-select"
            value={selectedConfig}
            onChange={e => setSelectedConfig(e.target.value)}
          >
            {configs.map(c => <option key={c.path} value={c.path}>{c.name}</option>)}
          </select>
          <button className="btn btn-primary btn-sm" onClick={() => setShowNewProject(true)}>
            + New Project
          </button>
          <button className="btn-icon cmd-k" onClick={() => setShowPalette(true)} title="⌘K">
            ⌘K
          </button>
          <div className={`conn-dot ${connected ? 'on' : ''}`} title={connected ? 'Connected' : 'Disconnected'} />
        </div>
      </nav>

      {/* ─── Content ─── */}
      <main className="content">
        {view === 'projects' ? (
          <ProjectList projects={allProjects} onSelect={handleSelectProject} onNew={() => setShowNewProject(true)} />
        ) : project ? (
          <>
            {/* Toolbar */}
            <div className="toolbar">
              <div className="toolbar-left">
                <h2 className="toolbar-title">{project.prompt.slice(0, 80)}</h2>
                <span className={`status-badge ${project.status}`}>{project.status}</span>
                <span className="toolbar-config">{project.config_name}</span>
              </div>
              <div className="toolbar-right">
                {project.status === 'running' && (
                  <button className="btn btn-outline btn-sm" onClick={handlePause}>⏸ Pause</button>
                )}
                {project.status === 'paused' && (
                  <button className="btn btn-outline btn-sm" onClick={handleResume}>▶ Resume</button>
                )}
                {(project.status === 'running' || project.status === 'paused') && (
                  <button className="btn btn-danger-outline btn-sm" onClick={handleKill}>⏹ Kill</button>
                )}
                <div className="toolbar-divider" />
                <button
                  className={`btn btn-ghost btn-sm ${showDecisions ? 'active' : ''}`}
                  onClick={() => { setShowDecisions(v => !v); setShowArtifacts(false) }}
                >
                  Decisions{decisions.length > 0 ? ` (${decisions.length})` : ''}
                </button>
                <button
                  className={`btn btn-ghost btn-sm ${showArtifacts ? 'active' : ''}`}
                  onClick={() => { setShowArtifacts(v => !v); setShowDecisions(false) }}
                >
                  Artifacts{artifacts.length > 0 ? ` (${artifacts.length})` : ''}
                </button>
                <div className="toolbar-divider" />
                <span className="toolbar-stats">
                  {project.total_input_tokens.toLocaleString()} in / {project.total_output_tokens.toLocaleString()} out · ${project.estimated_cost.toFixed(4)}
                </span>
              </div>
            </div>

            {/* Two-panel layout */}
            <div className="panels">
              <Pipeline
                events={events}
                selectedStep={selectedStep}
                onSelectStep={setSelectedStep}
                collapsed={pipelineCollapsed}
                onToggleCollapse={() => setPipelineCollapsed(v => !v)}
              />
              <div className="stream-panel">
                <ActivityStream events={events} selectedStep={selectedStep} />
                <UserInput onSend={handleSend} disabled={!project} />
              </div>
            </div>
          </>
        ) : null}
      </main>

      {/* ─── Overlays ─── */}
      {showPalette && (
        <CommandPalette
          projects={allProjects}
          configs={configs}
          activeProject={project}
          onSelectProject={handleSelectProject}
          onSelectConfig={setSelectedConfig}
          onNewProject={() => { setShowPalette(false); setShowNewProject(true) }}
          onPause={handlePause}
          onResume={handleResume}
          onKill={handleKill}
          onClose={() => setShowPalette(false)}
        />
      )}
      {showNewProject && (
        <NewProjectModal
          configs={configs}
          selectedConfig={selectedConfig}
          onChangeConfig={setSelectedConfig}
          onCreate={handleCreate}
          onClose={() => setShowNewProject(false)}
          loading={loading}
        />
      )}
      {showDecisions && <DecisionDrawer decisions={decisions} onClose={() => setShowDecisions(false)} />}
      {showArtifacts && <ArtifactDrawer artifacts={artifacts} onClose={() => setShowArtifacts(false)} />}
    </div>
  )
}
