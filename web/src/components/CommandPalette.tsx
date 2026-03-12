import { useState, useEffect, useRef, useMemo } from 'react'
import type { Project, ConfigInfo } from '../api'

interface CommandItem {
  id: string
  label: string
  hint?: string
  icon: string
  action: () => void
  category: string
}

interface Props {
  projects: Project[]
  configs: ConfigInfo[]
  activeProject: Project | null
  onSelectProject: (p: Project) => void
  onSelectConfig: (path: string) => void
  onNewProject: () => void
  onPause: () => void
  onResume: () => void
  onKill: () => void
  onClose: () => void
}

export default function CommandPalette({
  projects, configs, activeProject,
  onSelectProject, onSelectConfig, onNewProject,
  onPause, onResume, onKill, onClose,
}: Props) {
  const [query, setQuery] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const [selected, setSelected] = useState(0)

  useEffect(() => { inputRef.current?.focus() }, [])

  const items = useMemo<CommandItem[]>(() => {
    const cmds: CommandItem[] = [
      { id: 'new', label: 'New Project', icon: '＋', action: () => { onNewProject(); onClose() }, category: 'Actions' },
    ]

    if (activeProject?.status === 'running')
      cmds.push({ id: 'pause', label: 'Pause Project', icon: '⏸', action: () => { onPause(); onClose() }, category: 'Actions' })
    if (activeProject?.status === 'paused')
      cmds.push({ id: 'resume', label: 'Resume Project', icon: '▶', action: () => { onResume(); onClose() }, category: 'Actions' })
    if (activeProject && ['running', 'paused'].includes(activeProject.status))
      cmds.push({ id: 'kill', label: 'Kill Project', icon: '⏹', action: () => { onKill(); onClose() }, category: 'Actions' })

    for (const p of projects)
      cmds.push({
        id: `p-${p.id}`, label: p.prompt.slice(0, 60),
        hint: p.config_name,
        icon: p.status === 'running' ? '●' : p.status === 'completed' ? '✓' : '○',
        action: () => { onSelectProject(p); onClose() }, category: 'Projects',
      })

    for (const c of configs)
      cmds.push({
        id: `c-${c.path}`, label: c.name, hint: c.description,
        icon: '⚙', action: () => { onSelectConfig(c.path); onClose() }, category: 'Configs',
      })

    return cmds
  }, [projects, configs, activeProject, onSelectProject, onSelectConfig, onNewProject, onPause, onResume, onKill, onClose])

  const filtered = useMemo(() => {
    if (!query.trim()) return items
    const q = query.toLowerCase()
    return items.filter(i => i.label.toLowerCase().includes(q) || i.hint?.toLowerCase().includes(q))
  }, [items, query])

  useEffect(() => { setSelected(0) }, [filtered])

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') onClose()
    else if (e.key === 'ArrowDown') { e.preventDefault(); setSelected(i => Math.min(i + 1, filtered.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setSelected(i => Math.max(i - 1, 0)) }
    else if (e.key === 'Enter' && filtered[selected]) filtered[selected].action()
  }

  const grouped = useMemo(() => {
    const m = new Map<string, CommandItem[]>()
    for (const item of filtered) {
      if (!m.has(item.category)) m.set(item.category, [])
      m.get(item.category)!.push(item)
    }
    return m
  }, [filtered])

  let flatIdx = 0

  return (
    <div className="palette-overlay" onClick={onClose}>
      <div className="palette" onClick={e => e.stopPropagation()}>
        <input
          ref={inputRef}
          className="palette-input"
          value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={handleKey}
          placeholder="Type a command or search…"
        />
        <div className="palette-results">
          {filtered.length === 0 && <div className="palette-empty">No results</div>}
          {Array.from(grouped.entries()).map(([cat, catItems]) => (
            <div key={cat}>
              <div className="palette-category">{cat}</div>
              {catItems.map(item => {
                const idx = flatIdx++
                return (
                  <div
                    key={item.id}
                    className={`palette-item ${idx === selected ? 'selected' : ''}`}
                    onClick={item.action}
                    onMouseEnter={() => setSelected(idx)}
                  >
                    <span className="palette-item-icon">{item.icon}</span>
                    <span className="palette-item-label">{item.label}</span>
                    {item.hint && <span className="palette-item-hint">{item.hint}</span>}
                  </div>
                )
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
