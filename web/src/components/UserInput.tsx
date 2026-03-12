import { useState } from 'react'

interface Props {
  onSend: (action: string, message: string) => void
  disabled: boolean
}

export default function UserInput({ onSend, disabled }: Props) {
  const [message, setMessage] = useState('')

  function handleSend(action: string) {
    if (!message.trim()) return
    onSend(action, message.trim())
    setMessage('')
  }

  return (
    <div className="user-input">
      <input
        value={message}
        onChange={(e) => setMessage(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && handleSend('message')}
        placeholder={disabled ? 'Launch a project first...' : 'Send a message, constraint, or veto...'}
        disabled={disabled}
      />
      <div className="input-actions">
        <button className="primary" onClick={() => handleSend('message')} disabled={disabled || !message.trim()}>
          Send
        </button>
        <button onClick={() => handleSend('constrain')} disabled={disabled || !message.trim()}>
          Constrain
        </button>
        <button className="veto" onClick={() => handleSend('veto')} disabled={disabled || !message.trim()}>
          Veto
        </button>
      </div>
    </div>
  )
}
