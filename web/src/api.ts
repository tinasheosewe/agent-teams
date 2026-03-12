const API_BASE = '/api'

export interface Project {
  id: string
  prompt: string
  config_name: string
  status: string
  total_input_tokens: number
  total_output_tokens: number
  estimated_cost: number
}

export interface Decision {
  id: string
  topic: string
  decision: string
  rationale: string
  team: string
  status: string
  confidence: number
  created_at: string
}

export interface Artifact {
  id: string
  type: string
  name: string
  content: string
  version: number
  team: string
  status: string
  created_at: string
}

export interface ConfigInfo {
  path: string
  name: string
  description: string
  teams: string[]
}

export async function createProject(prompt: string, configPath?: string): Promise<Project> {
  const res = await fetch(`${API_BASE}/projects`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt, config_path: configPath || 'configs/overlays/software_company.yaml' }),
  })
  return res.json()
}

export async function runProject(projectId: string): Promise<Project> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/run`, { method: 'POST' })
  return res.json()
}

export async function getProject(projectId: string): Promise<Project> {
  const res = await fetch(`${API_BASE}/projects/${projectId}`)
  return res.json()
}

export async function listProjects(): Promise<Project[]> {
  const res = await fetch(`${API_BASE}/projects`)
  return res.json()
}

export async function getDecisions(projectId: string): Promise<Decision[]> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/decisions`)
  return res.json()
}

export async function getArtifacts(projectId: string): Promise<Artifact[]> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/artifacts`)
  return res.json()
}

export async function sendMessage(projectId: string, message: string, action: string = 'message'): Promise<void> {
  await fetch(`${API_BASE}/projects/${projectId}/message`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, action }),
  })
}

export async function pauseProject(projectId: string): Promise<{ status?: string; error?: string }> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/pause`, { method: 'POST' })
  return res.json()
}

export async function resumeProject(projectId: string): Promise<{ status?: string; error?: string }> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/resume`, { method: 'POST' })
  return res.json()
}

export async function killProject(projectId: string): Promise<{ status?: string; error?: string }> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/kill`, { method: 'POST' })
  return res.json()
}

export async function listConfigs(): Promise<ConfigInfo[]> {
  const res = await fetch(`${API_BASE}/configs`)
  return res.json()
}

export interface Escalation {
  id: string
  message: string
  data: Record<string, unknown>
  status: string
  created_at: string
}

export interface FileInfo {
  path: string
  size: number
}

export async function getEscalations(projectId: string): Promise<Escalation[]> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/escalations`)
  return res.json()
}

export async function getFiles(projectId: string): Promise<FileInfo[]> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/files`)
  return res.json()
}

export async function setMode(projectId: string, mode: 'interactive' | 'autonomous'): Promise<{ status?: string; mode?: string }> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/mode`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode }),
  })
  return res.json()
}
