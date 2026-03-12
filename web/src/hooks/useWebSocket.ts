import { useEffect, useRef, useCallback, useState } from 'react'

export interface WsEvent {
  type: string
  data: Record<string, unknown>
  timestamp: string
  project_id: string
}

export function useWebSocket(projectId: string | null) {
  const [events, setEvents] = useState<WsEvent[]>([])
  const [connected, setConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    if (!projectId) return

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/projects/${projectId}`)
    wsRef.current = ws

    ws.onopen = () => setConnected(true)

    ws.onmessage = (evt) => {
      try {
        const event: WsEvent = JSON.parse(evt.data)
        setEvents((prev) => [...prev, event])
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

  const clearEvents = useCallback(() => setEvents([]), [])

  return { events, connected, send, clearEvents }
}
