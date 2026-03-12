import { useEffect, useRef } from 'react'
import type { Toast } from '../hooks/useWebSocket'

const MAX_VISIBLE = 4
const AUTO_DISMISS_MS = 6000

const KIND_COLORS: Record<string, string> = {
  'low-confidence': 'var(--yellow)',
  'gate-return': 'var(--red)',
  'escalation': 'var(--orange, #fb923c)',
  'input-request': 'var(--accent)',
}

const KIND_ICONS: Record<string, string> = {
  'low-confidence': '◑',
  'gate-return': '↩',
  'escalation': '▲',
  'input-request': '◇',
}

interface Props {
  toasts: Toast[]
  onDismiss: (id: string) => void
  onNavigate: (stepName: string) => void
}

export default function ToastRail({ toasts, onDismiss, onNavigate }: Props) {
  const timersRef = useRef<Map<string, number>>(new Map())

  // Auto-dismiss
  useEffect(() => {
    const timers = timersRef.current
    for (const toast of toasts) {
      if (toast.dismissed || timers.has(toast.id)) continue
      const timer = window.setTimeout(() => {
        onDismiss(toast.id)
        timers.delete(toast.id)
      }, AUTO_DISMISS_MS)
      timers.set(toast.id, timer)
    }

    return () => {
      timers.forEach(t => window.clearTimeout(t))
      timers.clear()
    }
  }, [toasts, onDismiss])

  const visible = toasts.filter(t => !t.dismissed).slice(-MAX_VISIBLE)
  if (visible.length === 0) return null

  return (
    <div className="toast-rail" role="log" aria-label="Notifications">
      {visible.map((toast) => {
        const borderColor = KIND_COLORS[toast.kind] ?? 'var(--border)'
        const icon = KIND_ICONS[toast.kind] ?? '●'
        return (
          <div
            key={toast.id}
            className="toast"
            style={{ borderLeftColor: borderColor }}
            role="alert"
          >
            <span className="toast-icon" style={{ color: borderColor }}>{icon}</span>
            <div className="toast-body">
              <span className="toast-message">{toast.message}</span>
              {toast.stepName && (
                <button
                  className="toast-link"
                  onClick={() => onNavigate(toast.stepName!)}
                >
                  Go to {toast.stepName}
                </button>
              )}
            </div>
            <button
              className="toast-close"
              onClick={() => onDismiss(toast.id)}
              aria-label="Dismiss"
            >
              ×
            </button>
          </div>
        )
      })}
    </div>
  )
}
