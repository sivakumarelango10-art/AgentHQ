import { useEffect, useMemo, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import {
  Activity,
  Bot,
  Building2,
  CheckCircle2,
  ChevronDown,
  CircleHelp,
  Clock3,
  Cpu,
  LayoutDashboard,
  MessageSquareText,
  PanelLeftClose,
  Plus,
  Radio,
  Settings2,
  Sparkles,
  Users,
  Wifi,
} from 'lucide-react'
import { OfficeScene } from './components/office/OfficeScene'
import { initialAgents } from './data'
import type { Agent, BackendHealth } from './types'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000'

function App() {
  const [agents] = useState<Agent[]>(initialAgents)
  const [selectedAgentId, setSelectedAgentId] = useState('dev')
  const [backend, setBackend] = useState<BackendHealth | null>(null)
  const [showAgentDetails, setShowAgentDetails] = useState(true)
  const [cameraMode, setCameraMode] = useState<'orbit' | 'overview'>('orbit')

  const selectedAgent = useMemo(
    () => agents.find((agent) => agent.id === selectedAgentId) ?? agents[0],
    [agents, selectedAgentId],
  )

  useEffect(() => {
    let active = true
    const checkHealth = async () => {
      try {
        const response = await fetch(`${API_BASE}/api/health`, { signal: AbortSignal.timeout(2500) })
        if (!response.ok) throw new Error('Backend not ready')
        const data = (await response.json()) as BackendHealth
        if (active) setBackend(data)
      } catch {
        if (active) setBackend(null)
      }
    }
    void checkHealth()
    const timer = window.setInterval(checkHealth, 8000)
    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [])

  const activeCount = agents.filter((agent) => agent.status === 'working').length

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand-row">
          <div className="brand-mark"><Sparkles size={19} /></div>
          <div>
            <div className="brand-name">Agent<span>HQ</span></div>
            <div className="brand-caption">YOUR AI COMPANY</div>
          </div>
          <button className="icon-button sidebar-collapse" aria-label="Collapse sidebar"><PanelLeftClose size={17} /></button>
        </div>

        <div className="workspace-switcher">
          <div className="workspace-icon"><Building2 size={17} /></div>
          <div className="workspace-copy"><strong>My Startup</strong><span>Local workspace</span></div>
          <ChevronDown size={15} className="muted-icon" />
        </div>

        <div className="nav-label">WORKSPACE</div>
        <nav className="main-nav">
          <button className="nav-item active"><LayoutDashboard size={17} />Office overview</button>
          <button className="nav-item"><Users size={17} />Employees <span className="nav-count">{agents.length}</span></button>
          <button className="nav-item"><Activity size={17} />Tasks <span className="nav-count">0</span></button>
          <button className="nav-item"><MessageSquareText size={17} />Conversations</button>
        </nav>

        <div className="nav-label departments-label">DEPARTMENTS</div>
        <div className="department-list">
          <div><span className="dept-dot dot-teal" />Management</div>
          <div><span className="dept-dot dot-blue" />Engineering</div>
          <div><span className="dept-dot dot-pink" />Design Studio</div>
          <div><span className="dept-dot dot-orange" />Quality & Testing</div>
        </div>

        <div className="sidebar-bottom">
          <div className="local-card">
            <div className="local-card-top"><span className="pulse-dot" /> LOCAL AI RUNTIME</div>
            <strong>{backend?.ollama_connected ? 'Ollama connected' : 'Waiting for backend'}</strong>
            <span>{backend?.model ?? 'Start the AgentHQ API'}</span>
            <div className="local-card-foot"><Wifi size={13} /> No cloud API configured</div>
          </div>
          <button className="nav-item settings-item"><Settings2 size={17} />Settings</button>
          <button className="nav-item"><CircleHelp size={17} />Help & documentation</button>
          <div className="version-line">AGENTHQ PREVIEW <span>v0.1.0</span></div>
        </div>
      </aside>

      <section className="main-area">
        <header className="topbar">
          <div className="breadcrumb"><span>Workspace</span><span className="crumb-sep">/</span><strong>Office overview</strong></div>
          <div className="topbar-actions">
            <div className={`connection-pill ${backend ? 'connected' : ''}`}><span className="connection-dot" />{backend ? 'Backend connected' : 'Backend offline'}</div>
            <button className="avatar-button" title="Founder profile">F</button>
          </div>
        </header>

        <div className="content-wrap">
          <div className="page-heading">
            <div>
              <div className="eyebrow"><span className="eyebrow-line" /> YOUR WORKSPACE IS READY</div>
              <h1>Good afternoon, Founder <span className="wave">✦</span></h1>
              <p>Here’s what’s happening inside your company today.</p>
            </div>
            <button className="primary-button" onClick={() => window.alert('Task creation will be enabled in Phase 2.') }><Plus size={16} /> Create task</button>
          </div>

          <div className="metric-grid">
            <Metric icon={<Users size={17} />} label="Total employees" value={String(agents.length).padStart(2, '0')} foot="Across all departments" tone="teal" />
            <Metric icon={<Activity size={17} />} label="Currently working" value={String(activeCount).padStart(2, '0')} foot="Preview employee states" tone="green" />
            <Metric icon={<CheckCircle2 size={17} />} label="Tasks completed" value="00" foot="No tasks executed yet" tone="blue" />
            <Metric icon={<Clock3 size={17} />} label="Average response" value="—" foot="Available after AI setup" tone="amber" />
          </div>

          <div className="office-section-heading">
            <div><h2>Live office</h2><span className="live-tag"><span className="live-dot" />3D PREVIEW</span></div>
            <div className="office-toolbar">
              <button className={`tool-button ${cameraMode === 'orbit' ? 'selected' : ''}`} onClick={() => setCameraMode('orbit')}>Explore</button>
              <button className={`tool-button ${cameraMode === 'overview' ? 'selected' : ''}`} onClick={() => setCameraMode('overview')}>Overview</button>
              <button className="tool-button agent-toggle" onClick={() => setShowAgentDetails((value) => !value)}><Users size={14} /> Team</button>
            </div>
          </div>

          <div className={`office-layout ${showAgentDetails ? '' : 'hide-details'}`}>
            <div className="scene-frame">
              <div className="scene-top-label"><span className="scene-live-icon"><Radio size={13} /></span> AGENTHQ CAMPUS <span className="scene-divider">·</span> FLOOR 01</div>
              <OfficeScene agents={agents} selectedAgentId={selectedAgentId} onSelectAgent={setSelectedAgentId} cameraMode={cameraMode} />
              <div className="scene-bottom-hint"><span className="mouse-icon">⌖</span> DRAG TO ROTATE <span>·</span> SCROLL TO ZOOM <span>·</span> CLICK AN EMPLOYEE</div>
            </div>

            {showAgentDetails && <aside className="team-panel">
              <div className="panel-heading"><div><h3>People at work</h3><p>{agents.length} employees in your office</p></div><button className="icon-button" aria-label="Team options"><Settings2 size={15} /></button></div>
              <div className="team-list">
                {agents.map((agent) => <button key={agent.id} className={`agent-row ${selectedAgentId === agent.id ? 'agent-selected' : ''}`} onClick={() => setSelectedAgentId(agent.id)}>
                  <div className="agent-avatar" style={{ '--agent-color': agent.color } as CSSProperties}>{agent.name.slice(0, 1)}</div>
                  <div className="agent-info"><strong>{agent.name}</strong><span>{agent.role}</span><small>{agent.room}</small></div>
                  <span className={`status-dot status-${agent.status}`} title={agent.status} />
                </button>)}
              </div>
              <div className="selected-agent-card">
                <div className="selected-label">SELECTED EMPLOYEE</div>
                <div className="selected-agent-heading"><div className="agent-avatar large" style={{ '--agent-color': selectedAgent.color } as CSSProperties}>{selectedAgent.name.slice(0, 1)}</div><div><strong>{selectedAgent.name}</strong><span>{selectedAgent.role}</span></div></div>
                <div className="current-task-label">CURRENT ACTIVITY</div>
                <p>{selectedAgent.currentTask}</p>
                <div className="selected-room"><Building2 size={13} />{selectedAgent.room}</div>
              </div>
              <button className="panel-add-button" onClick={() => window.alert('Employee creation will be enabled in Phase 2.')}><Plus size={15} /> Add employee</button>
            </aside>}
          </div>

          <div className="bottom-note"><Cpu size={15} /><span>Running locally on your PC</span><span className="note-separator">·</span><span>{backend?.ollama_connected ? 'Ollama is reachable' : 'AI runtime connection will be configured next'}</span></div>
        </div>
      </section>
    </main>
  )
}

function Metric({ icon, label, value, foot, tone }: { icon: ReactNode; label: string; value: string; foot: string; tone: string }) {
  return <div className="metric-card"><div className={`metric-icon ${tone}`}>{icon}</div><div className="metric-label">{label}</div><div className="metric-value">{value}</div><div className="metric-foot">{foot}</div></div>
}

export default App
