import { useState, useEffect } from 'react'
import './App.css'

type State = 'standby' | 'listening' | 'processing' | 'speaking'

export default function App() {
  const [state, setState] = useState<State>('standby')

  useEffect(() => {
    let ws: WebSocket
    let dead = false

    function connect() {
      if (dead) return
      ws = new WebSocket('ws://localhost:7788')
      ws.onopen  = () => console.log('[ws] connected')
      ws.onmessage = e => {
        try {
          const { state: s } = JSON.parse(e.data) as { state: State }
          if (s) setState(s)
        } catch {}
      }
      ws.onclose = () => { if (!dead) setTimeout(connect, 1500) }
    }

    connect()
    return () => { dead = true; ws?.close() }
  }, [])

  return (
    <div className="scene" data-state={state}>
      <div className="glow" />
      <div className="dot" />
      {state === 'processing' && <div className="arc" />}
      {state === 'speaking' && (
        <>
          <div className="ripple" style={{ '--d': '0s'   } as React.CSSProperties} />
          <div className="ripple" style={{ '--d': '0.4s' } as React.CSSProperties} />
          <div className="ripple" style={{ '--d': '0.8s' } as React.CSSProperties} />
        </>
      )}
    </div>
  )
}
