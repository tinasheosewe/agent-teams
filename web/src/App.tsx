import { useState, useEffect, useCallback } from 'react'
import { createProject, runProject, getProject, getDecisions, getArtifacts, listProjects } from './api'
import type { Project, Decision, Artifact } from './api'
import { useWebSocket } from './hooks/useWebSocket'
import Dashboard from './components/Dashboard'
import ConversationView from './components/ConversationView'
import DecisionLog from './components/DecisionLog'
import ArtifactViewer from './components/ArtifactViewer'
import UserInput from './components/UserInput'

export default function App() {
  const [prompt, setPrompt] = useState('')
  const [project, setProject] = useState<Project | null>(null)
  const [decisions, setDecisions] = useState<Decision[]>([])
  const [artifacts, setArtifacts] = useState<Artifact[]>([])
  const [loading, setLoading] = useState(false)

  const { events, connected, send } = useWebSocket(project?.id ?? null)

  // On mount, load the most recent active project (if any)
  useEffect(() => {
    listProjects().then((projects) => {
      const active = projects.find((p) => p.status === 'running') ?? projects[projects.length - 1]
      if (active) {
        setProject(active)
        setPrompt(active.prompt)
      }
    }).catch(() => {})
  }, [])

  // Poll for project status + decisions + artifacts when running
  useEffect(() => {
    if (!project || project.status === 'completed' || project.status === 'failed') return

    const interval = setInterval(async () => {
      const updated = await getProject(project.id)
      setProject(updated)
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
      const p = await createProject(prompt)
      setProject(p)
      const running = await runProject(p.id)
      setProject(running)
    } finally {
      setLoading(false)
    }
  }, [prompt])

  const handleUserInput = useCallback(
    (action: string, message: string) => {
      send(action, message)
    },
    [send],
  )

  return (
    <div className="app">
      {/* Header */}
      <div className="header">
        <h1>AgentAgent</h1>
        <span className="status">
          {project ? `${project.config_name} — ${project.status}` : 'No project'}
          {connected && ' • Connected'}
        </span>
        <span className="cost">
          {project ? `$${project.estimated_cost.toFixed(4)}` : '$0.0000'}
        </span>
      </div>

      {/* Create project form */}
      <div className="create-form">
        <input
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
          placeholder="Describe your project idea... (e.g., 'Build a landing page for selling artisan dog food')"
          disabled={loading}
        />
        <button onClick={handleCreate} disabled={loading || !prompt.trim()}>
          {loading ? 'Starting...' : 'Launch Project'}
        </button>
      </div>

      {/* Main layout */}
      <div className="main">
        {/* Left sidebar — workflow pipeline */}
        <Dashboard events={events} />

        {/* Center — conversation stream */}
        <div className="conversation">
          <ConversationView events={events} />
          <UserInput onSend={handleUserInput} disabled={!project} />
        </div>

        {/* Right panel — decisions + artifacts */}
        <div className="panel">
          <div className="panel-section">
            <h2>Decisions ({decisions.length})</h2>
            <DecisionLog decisions={decisions} />
          </div>
          <div className="panel-section">
            <h2>Artifacts ({artifacts.length})</h2>
            <ArtifactViewer artifacts={artifacts} />
          </div>
        </div>
      </div>
    </div>
  )
}
