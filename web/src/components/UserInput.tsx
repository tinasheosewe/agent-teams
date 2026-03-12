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
        placeholder={disabled ? 'Start a project first...' : 'Send a message...'}
        disabled={disabled}
      />
      <button onClick={() => handleSend('message')} disabled={disabled}>
        Send
      </button>
      <button onClick={() => handleSend('constrain')} disabled={disabled}>
        Constrain
      </button>
      <button className="veto" onClick={() => handleSend('veto')} disabled={disabled}>
        Veto
      </button>
    </div>
  )
}
