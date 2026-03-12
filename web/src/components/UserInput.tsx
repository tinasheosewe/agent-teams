import { useState } from 'react'

interface Props {
  onSend: (action: string, message: string) => void
  disabled: boolean
}

export default function UserInput({ onSend, disabled }: Props) {
  const [message, setMessage] = useState('')

  function send(action: string) {
    if (!message.trim()) return
    onSend(action, message.trim())
    setMessage('')
  }

  return (
    <div className="user-input">
      <input
        value={message}
        onChange={e => setMessage(e.target.value)}
        onKeyDown={e => e.key === 'Enter' && send('message')}
        placeholder={disabled ? 'Launch a project first…' : 'Send a message, constraint, or veto…'}
        disabled={disabled}
      />
      <div className="input-actions">
        <button className="btn btn-primary btn-sm" onClick={() => send('message')} disabled={disabled || !message.trim()}>
          Send <kbd>↵</kbd>
        </button>
        <button className="btn btn-outline btn-sm" onClick={() => send('constrain')} disabled={disabled || !message.trim()}>
          Constrain
        </button>
        <button className="btn btn-danger-outline btn-sm" onClick={() => send('veto')} disabled={disabled || !message.trim()}>
          Veto
        </button>
      </div>
    </div>
  )
}
