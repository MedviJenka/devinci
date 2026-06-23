import { useState, useEffect, useRef } from 'react'
import './App.css'

type State   = 'standby' | 'listening' | 'processing' | 'speaking'
type Level   = 'info' | 'transcript' | 'response' | 'error'
type Tab     = 'logs' | 'status' | 'settings'

interface LogEntry { ts: number; level: Level; text: string }
interface Config {
  working_dir: string; session_window: number
  energy_threshold: number; wake_phrases: string[]; ws_port: number
}

const STATE_COLOR: Record<State, string> = {
  standby:    '#508cff',
  listening:  '#00dc82',
  processing: '#ff9400',
  speaking:   '#a050ff',
}

function fmt(ts: number) {
  return new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export default function App() {
  const [state,     setState]    = useState<State>('standby')
  const [logs,      setLogs]     = useState<LogEntry[]>([])
  const [config,    setConfig]   = useState<Config | null>(null)
  const [connected, setConnected] = useState(false)
  const [dashOpen,  setDashOpen] = useState(false)
  const [tab,       setTab]      = useState<Tab>('logs')
  const [uptime,    setUptime]   = useState('00:00:00')
  const startMs   = useRef(Date.now())
  const logsEnd   = useRef<HTMLDivElement>(null)

  // uptime
  useEffect(() => {
    const iv = setInterval(() => {
      const s = Math.floor((Date.now() - startMs.current) / 1000)
      setUptime([
        String(Math.floor(s / 3600)).padStart(2, '0'),
        String(Math.floor((s % 3600) / 60)).padStart(2, '0'),
        String(s % 60).padStart(2, '0'),
      ].join(':'))
    }, 1000)
    return () => clearInterval(iv)
  }, [])

  // websocket
  useEffect(() => {
    let ws: WebSocket, dead = false
    function connect() {
      if (dead) return
      ws = new WebSocket('ws://localhost:7788')
      ws.onopen  = () => setConnected(true)
      ws.onclose = () => { setConnected(false); if (!dead) setTimeout(connect, 1500) }
      ws.onmessage = e => {
        try {
          const m = JSON.parse(e.data)
          if      (m.type === 'state')  setState(m.state)
          else if (m.type === 'log')    setLogs(prev => [...prev.slice(-299), m as LogEntry])
          else if (m.type === 'config') setConfig(m as Config)
          else if (m.state)             setState(m.state)
        } catch {}
      }
    }
    connect()
    return () => { dead = true; ws?.close() }
  }, [])

  // auto-scroll logs
  useEffect(() => {
    if (tab === 'logs') logsEnd.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs, tab])

  function toggleDash() {
    const next = !dashOpen
    setDashOpen(next)
    ;(window as any).electron?.toggleDashboard(next)
  }

  // ── closed: just the dot ──────────────────────────────────────────────────
  if (!dashOpen) {
    return (
      <div className="scene" data-state={state}>
        <div className="glow" />
        <div className="dot" onClick={toggleDash} title="Open dashboard" />
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

  // ── open: dashboard ───────────────────────────────────────────────────────
  return (
    <div className="dashboard">

      {/* header */}
      <div className="dash-header">
        <span className="dash-indicator" style={{ background: STATE_COLOR[state] }} />
        <span className="dash-title">Claude Listener</span>
        <span className={`dash-ws ${connected ? 'ok' : 'err'}`}>{connected ? '● live' : '○ offline'}</span>
        <button className="dash-close" onClick={toggleDash}>✕</button>
      </div>

      {/* tabs */}
      <div className="tab-bar">
        {(['logs', 'status', 'settings'] as Tab[]).map(t => (
          <button key={t} className={`tab ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {/* content */}
      <div className="tab-body">

        {/* ── logs ── */}
        {tab === 'logs' && (
          <div className="log-list">
            {logs.length === 0 && <p className="empty">Waiting for activity…</p>}
            {logs.map((l, i) => (
              <div key={i} className={`log-row lvl-${l.level}`}>
                <span className="log-ts">{fmt(l.ts)}</span>
                <span className="log-badge">{l.level}</span>
                <span className="log-text">{l.text}</span>
              </div>
            ))}
            <div ref={logsEnd} />
          </div>
        )}

        {/* ── status ── */}
        {tab === 'status' && (
          <div className="stat-grid">
            {[
              ['State',       <span style={{ color: STATE_COLOR[state], fontWeight: 700 }}>{state}</span>],
              ['Uptime',      <code>{uptime}</code>],
              ['WebSocket',   <span className={connected ? 'ok' : 'err'}>{connected ? 'connected' : 'disconnected'}</span>],
              ['Log entries', <code>{logs.length}</code>],
            ].map(([label, value]) => (
              <div key={String(label)} className="stat-row">
                <span className="stat-lbl">{label}</span>
                <span className="stat-val">{value}</span>
              </div>
            ))}
          </div>
        )}

        {/* ── settings ── */}
        {tab === 'settings' && (
          <div className="settings-list">
            {!config && <p className="empty">Config not yet received…</p>}
            {config && Object.entries({
              'Working dir':       config.working_dir,
              'WS port':           String(config.ws_port),
              'Session window':    `${config.session_window}s`,
              'Energy threshold':  String(config.energy_threshold),
              'Wake phrases':      config.wake_phrases.join(', '),
            }).map(([k, v]) => (
              <div key={k} className="setting-row">
                <span className="setting-lbl">{k}</span>
                <span className="setting-val">{v}</span>
              </div>
            ))}
          </div>
        )}

      </div>
    </div>
  )
}
