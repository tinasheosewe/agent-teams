import { useEffect, useRef, useCallback, useState } from 'react'

export interface WsEvent {
  type: string
  data: Record<string, unknown>
  timestamp: string
  project_id: string
}

export interface Toast {
  id: string
  kind: 'error' | 'warning' | 'info'
  message: string
  stepName?: string
  timestamp: string
  dismissed: boolean
}

let toastSeq = 0

function extractToast(evt: WsEvent): Toast | null {
  if (evt.type === 'decision_made') {
    const conf = Number(evt.data.confidence ?? 1)
    if (conf < 0.6) {
      return {
        id: `toast-${++toastSeq}`,
        kind: conf < 0.4 ? 'error' : 'warning',
        message: `Low confidence decision: ${String(evt.data.topic ?? 'unknown')} (${(conf * 100).toFixed(0)}%)`,
        stepName: String(evt.data.step ?? ''),
        timestamp: evt.timestamp,
        dismissed: false,
      }
    }
  }
  if (evt.type === 'forum_gate_result') {
    const result = String(evt.data.result ?? '').toLowerCase()
    if (result.includes('return')) {
      return {
        id: `toast-${++toastSeq}`,
        kind: 'error',
        message: `Gate returned: ${String(evt.data.step ?? evt.data.gate ?? 'unknown')}`,
        stepName: String(evt.data.step ?? ''),
        timestamp: evt.timestamp,
        dismissed: false,
      }
    }
  }
  if (evt.type === 'forum_escalation') {
    return {
      id: `toast-${++toastSeq}`,
      kind: 'warning',
      message: `Escalation: ${String(evt.data.message ?? '')}`.slice(0, 120),
      timestamp: evt.timestamp,
      dismissed: false,
    }
  }
  if (evt.type === 'user_input_requested') {
    return {
      id: `toast-${++toastSeq}`,
      kind: 'info',
      message: `Input requested by ${String(evt.data.team ?? 'team')}`,
      stepName: String(evt.data.step ?? ''),
      timestamp: evt.timestamp,
      dismissed: false,
    }
  }
  return null
}

export function useWebSocket(projectId: string | null) {
  const [events, setEvents] = useState<WsEvent[]>([])
  const [toasts, setToasts] = useState<Toast[]>([])
  const [connected, setConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    if (!projectId) return

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/projects/${projectId}`)
    wsRef.current = ws

    ws.onopen = () => setConnected(true)

    ws.onmessage = (msg) => {
      try {
        const event: WsEvent = JSON.parse(msg.data)
        setEvents((prev) => [...prev, event])
        const toast = extractToast(event)
        if (toast) setToasts((prev) => [...prev, toast])
      } catch {
        // ignore malformed messages
      }
    }

    ws.onclose = () => setConnected(false)
    ws.onerror = () => setConnected(false)

    return () => {
      ws.close()
      wsRef.current = null
    }
  }, [projectId])

  const send = useCallback(
    (action: string, message: string) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ action, message }))
      }
    },
    [],
  )

  const clearEvents = useCallback(() => {
    setEvents([])
    setToasts([])
  }, [])

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.map(t => t.id === id ? { ...t, dismissed: true } : t))
  }, [])

  return { events, toasts, connected, send, clearEvents, dismissToast }
}
