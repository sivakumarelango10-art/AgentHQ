import { useCallback, useEffect, useMemo, useState } from 'react'
import type { CSSProperties, FormEvent, ReactNode } from 'react'
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
  ListTodo,
  X,
  UserPlus,
  Ban,
  RefreshCw,
} from 'lucide-react'
import { OfficeScene } from './components/office/OfficeScene'
import { ConversationsView } from './components/chat/ConversationsView'
import { initialAgents } from './data'
import { addAgent, addTask, cancelTask, getAgents, getHealth, getTasks } from './api'
import type { Agent, AgentCreateInput, BackendHealth, Task, TaskCreateInput, TaskPriority } from './types'

 type View = 'overview' | 'employees' | 'tasks' | 'conversations'

function App() {
  const [agents, setAgents] = useState<Agent[]>(initialAgents)
  const [tasks, setTasks] = useState<Task[]>([])
  const [selectedAgentId, setSelectedAgentId] = useState('dev')
  const [backend, setBackend] = useState<BackendHealth | null>(null)
  const [apiError, setApiError] = useState<string | null>(null)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [showAgentDetails, setShowAgentDetails] = useState(true)
  const [cameraMode, setCameraMode] = useState<'orbit' | 'overview'>('orbit')
  const [activeView, setActiveView] = useState<View>('overview')
  const [taskModalOpen, setTaskModalOpen] = useState(false)
  const [employeeModalOpen, setEmployeeModalOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  const refreshData = useCallback(async (showSpinner = false) => {
    if (showSpinner) setIsRefreshing(true)
    try {
      const [healthData, agentData, taskData] = await Promise.all([getHealth(), getAgents(), getTasks()])
      setBackend(healthData)
      setAgents(agentData)
      setTasks(taskData)
      setApiError(null)
      setSelectedAgentId((current) => agentData.some((agent) => agent.id === current) ? current : (agentData[0]?.id ?? ''))
    } catch (error) {
      setApiError(error instanceof Error ? error.message : 'Could not reach the AgentHQ API.')
      setBackend(null)
    } finally {
      if (showSpinner) setIsRefreshing(false)
    }
  }, [])

  useEffect(() => {
    void refreshData()
    const timer = window.setInterval(() => void refreshData(), 6000)
    return () => window.clearInterval(timer)
  }, [refreshData])

  const selectedAgent = useMemo(
    () => agents.find((agent) => agent.id === selectedAgentId) ?? agents[0],
    [agents, selectedAgentId],
  )
  const activeCount = agents.filter((agent) => agent.status === 'working').length
  const queuedCount = tasks.filter((task) => task.status === 'queued').length

  const handleCreateTask = async (input: TaskCreateInput): Promise<string | null> => {
    setSaving(true)
    try {
      const task = await addTask(input)
      setTasks((current) => [task, ...current])
      setTaskModalOpen(false)
      setNotice(`Task “${task.title}” was saved to the local task queue.`)
      window.setTimeout(() => setNotice(null), 4500)
      return null
    } catch (error) {
      return error instanceof Error ? error.message : 'Unable to create task.'
    } finally {
      setSaving(false)
    }
  }

  const handleCreateEmployee = async (input: AgentCreateInput): Promise<string | null> => {
    setSaving(true)
    try {
      const agent = await addAgent(input)
      setAgents((current) => [...current, agent])
      setSelectedAgentId(agent.id)
      setEmployeeModalOpen(false)
      setNotice(`${agent.name} was added to the employee directory.`)
      window.setTimeout(() => setNotice(null), 4500)
      return null
    } catch (error) {
      return error instanceof Error ? error.message : 'Unable to add employee.'
    } finally {
      setSaving(false)
    }
  }

  const handleCancelTask = async (taskId: string) => {
    try {
      const updated = await cancelTask(taskId)
      setTasks((current) => current.map((task) => task.id === taskId ? updated : task))
      setNotice('Task cancelled.')
      window.setTimeout(() => setNotice(null), 3500)
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Unable to cancel task.')
    }
  }

  const openTaskModal = () => setTaskModalOpen(true)

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
          <button className={`nav-item ${activeView === 'overview' ? 'active' : ''}`} onClick={() => setActiveView('overview')}><LayoutDashboard size={17} />Office overview</button>
          <button className={`nav-item ${activeView === 'employees' ? 'active' : ''}`} onClick={() => setActiveView('employees')}><Users size={17} />Employees <span className="nav-count">{agents.length}</span></button>
          <button className={`nav-item ${activeView === 'tasks' ? 'active' : ''}`} onClick={() => setActiveView('tasks')}><Activity size={17} />Tasks <span className="nav-count">{queuedCount}</span></button>
          <button className={`nav-item ${activeView === 'conversations' ? 'active' : ''}`} onClick={() => setActiveView('conversations')}><MessageSquareText size={17} />Conversations</button>
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
            <strong>{backend?.ollama_connected ? 'Ollama connected' : 'Ollama not connected'}</strong>
            <span>{backend?.model ?? 'Backend uses local mode'}</span>
            <div className="local-card-foot"><Wifi size={13} /> No cloud API configured</div>
          </div>
          <button className="nav-item settings-item" onClick={() => setNotice('Settings will be added in a later milestone.')}><Settings2 size={17} />Settings</button>
          <button className="nav-item" onClick={() => setNotice('See README_PHASE2.md for this milestone guide.')}><CircleHelp size={17} />Help & documentation</button>
          <div className="version-line">AGENTHQ LOCAL <span>v0.2.0</span></div>
        </div>
      </aside>

      <section className="main-area">
        <header className="topbar">
          <div className="breadcrumb"><span>Workspace</span><span className="crumb-sep">/</span><strong>{activeView === 'overview' ? 'Office overview' : activeView === 'employees' ? 'Employees' : activeView === 'tasks' ? 'Tasks' : 'Conversations'}</strong></div>
          <div className="topbar-actions">
            <div className={`connection-pill ${backend ? 'connected' : ''}`}><span className="connection-dot" />{backend ? 'Backend connected' : 'Backend offline'}</div>
            <button className="icon-button refresh-button" onClick={() => void refreshData(true)} aria-label="Refresh local data" title="Refresh local data"><RefreshCw size={15} className={isRefreshing ? 'spin' : ''} /></button>
            <button className="avatar-button" title="Founder profile">F</button>
          </div>
        </header>

        <div className="content-wrap">
          {apiError && <div className="inline-alert"><Wifi size={15} />{apiError}. Start the backend and refresh. Preview employee data may be shown until it reconnects.</div>}
          {notice && <div className="toast-notice" role="status"><CheckCircle2 size={15} />{notice}<button aria-label="Dismiss notification" onClick={() => setNotice(null)}><X size={14} /></button></div>}

          {activeView === 'overview' && (
            <>
              <div className="page-heading">
                <div>
                  <div className="eyebrow"><span className="eyebrow-line" /> YOUR WORKSPACE IS READY</div>
                  <h1>Good afternoon, Founder <span className="wave">✦</span></h1>
                  <p>Your employee directory and task queue are now stored locally.</p>
                </div>
                <button className="primary-button" onClick={openTaskModal}><Plus size={16} /> Create task</button>
              </div>

              <div className="metric-grid">
                <Metric icon={<Users size={17} />} label="Total employees" value={String(agents.length).padStart(2, '0')} foot="SQLite employee records" tone="teal" />
                <Metric icon={<Activity size={17} />} label="Currently working" value={String(activeCount).padStart(2, '0')} foot="No execution worker yet" tone="green" />
                <Metric icon={<ListTodo size={17} />} label="Tasks in queue" value={String(queuedCount).padStart(2, '0')} foot="Saved, awaiting AI execution" tone="blue" />
                <Metric icon={<Clock3 size={17} />} label="AI response time" value="—" foot="Measured after execution is added" tone="amber" />
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

                {showAgentDetails && selectedAgent && <aside className="team-panel">
                  <div className="panel-heading"><div><h3>People at work</h3><p>{agents.length} employees in your office</p></div><button className="icon-button" aria-label="Team options" onClick={() => setActiveView('employees')}><Settings2 size={15} /></button></div>
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
                  <button className="panel-add-button" onClick={() => setEmployeeModalOpen(true)}><Plus size={15} /> Add employee</button>
                </aside>}
              </div>
              <div className="bottom-note"><Cpu size={15} /><span>Running locally on your PC</span><span className="note-separator">·</span><span>{backend?.ollama_connected ? 'Ollama is reachable' : 'Task and employee data are local'}</span></div>
            </>
          )}

          {activeView === 'employees' && (
            <section className="management-view">
              <div className="page-heading">
                <div><div className="eyebrow"><span className="eyebrow-line" /> COMPANY DIRECTORY</div><h1>Employees</h1><p>Persistent employee profiles stored in your local SQLite database.</p></div>
                <button className="primary-button" onClick={() => setEmployeeModalOpen(true)}><UserPlus size={16} /> Add employee</button>
              </div>
              <div className="directory-grid">
                {agents.map((agent) => <button key={agent.id} className="directory-card" onClick={() => { setSelectedAgentId(agent.id); setActiveView('overview') }}>
                  <div className="directory-card-top"><div className="agent-avatar directory-avatar" style={{ '--agent-color': agent.color } as CSSProperties}>{agent.name.slice(0, 1)}</div><span className={`status-pill status-${agent.status}`}>{agent.status}</span></div>
                  <strong>{agent.name}</strong><span className="directory-role">{agent.role}</span><span className="directory-meta">{agent.department} · {agent.room}</span>
                  <span className="directory-activity">{agent.currentTask}</span>
                </button>)}
              </div>
              <div className="info-strip"><Bot size={16} /><span>Employee profiles are persistent. Role-aware local AI conversations are available; task execution will be introduced separately.</span></div>
            </section>
          )}

          {activeView === 'tasks' && (
            <section className="management-view">
              <div className="page-heading">
                <div><div className="eyebrow"><span className="eyebrow-line" /> WORK MANAGEMENT</div><h1>Task inbox</h1><p>Create work items and assign them to employees. Execution is not enabled yet.</p></div>
                <button className="primary-button" onClick={openTaskModal}><Plus size={16} /> Create task</button>
              </div>
              <div className="task-summary-row">
                <div className="task-summary-card"><span>Queued</span><strong>{queuedCount}</strong></div>
                <div className="task-summary-card"><span>Cancelled</span><strong>{tasks.filter((task) => task.status === 'cancelled').length}</strong></div>
                <div className="task-summary-card"><span>Total saved</span><strong>{tasks.length}</strong></div>
              </div>
              {tasks.length === 0 ? <div className="empty-state"><div className="empty-icon"><ListTodo size={23} /></div><h3>Your task inbox is empty</h3><p>Create your first task and assign it to one of your AI employees.</p><button className="primary-button" onClick={openTaskModal}><Plus size={15} /> Create first task</button></div> : <div className="task-list">
                {tasks.map((task) => <article key={task.id} className={`task-card task-${task.status}`}>
                  <div className="task-card-main"><div className="task-heading-line"><h3>{task.title}</h3><span className={`priority-pill priority-${task.priority}`}>{task.priority}</span></div>
                    {task.description && <p>{task.description}</p>}
                    <div className="task-meta"><span><Users size={13} />{task.assigned_agent_name ? `${task.assigned_agent_name} · ${task.assigned_agent_role}` : 'Unassigned'}</span><span><Clock3 size={13} />{new Date(task.created_at).toLocaleString()}</span></div>
                  </div>
                  <div className="task-card-actions"><span className={`task-status-pill ${task.status}`}>{task.status === 'queued' ? 'Queued · not started' : 'Cancelled'}</span>{task.status === 'queued' && <button className="cancel-task-button" onClick={() => void handleCancelTask(task.id)}><Ban size={13} /> Cancel</button>}</div>
                </article>)}
              </div>}
              <div className="info-strip"><Clock3 size={16} /><span>Queued means saved for future execution. No employee will claim or complete a task until the AI execution engine is implemented.</span></div>
            </section>
          )}

          {activeView === 'conversations' && <ConversationsView agents={agents} />}
        </div>
      </section>

      {taskModalOpen && <TaskModal agents={agents} saving={saving} onClose={() => setTaskModalOpen(false)} onSubmit={handleCreateTask} />}
      {employeeModalOpen && <EmployeeModal saving={saving} onClose={() => setEmployeeModalOpen(false)} onSubmit={handleCreateEmployee} />}
    </main>
  )
}

function Metric({ icon, label, value, foot, tone }: { icon: ReactNode; label: string; value: string; foot: string; tone: string }) {
  return <div className="metric-card"><div className={`metric-icon ${tone}`}>{icon}</div><div className="metric-label">{label}</div><div className="metric-value">{value}</div><div className="metric-foot">{foot}</div></div>
}

function TaskModal({ agents, saving, onClose, onSubmit }: { agents: Agent[]; saving: boolean; onClose: () => void; onSubmit: (input: TaskCreateInput) => Promise<string | null> }) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [priority, setPriority] = useState<TaskPriority>('normal')
  const [assignedAgentId, setAssignedAgentId] = useState('')
  const [error, setError] = useState<string | null>(null)

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!title.trim()) { setError('Enter a task title.'); return }
    setError(null)
    const result = await onSubmit({ title: title.trim(), description: description.trim(), priority, assigned_agent_id: assignedAgentId || null })
    setError(result)
  }

  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !saving) onClose() }}>
    <form className="modal-card" onSubmit={(event) => void submit(event)}>
      <div className="modal-heading"><div><span className="modal-eyebrow">WORK MANAGEMENT</span><h2>Create task</h2><p>Save a task to the local queue and optionally assign an employee.</p></div><button type="button" className="icon-button modal-close" onClick={onClose} aria-label="Close"><X size={18} /></button></div>
      <label className="form-field"><span>Task title <b>*</b></span><input autoFocus maxLength={120} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="e.g. Build the employee profile page" required /></label>
      <label className="form-field"><span>Description</span><textarea maxLength={2500} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Describe the expected outcome, context and constraints..." rows={4} /></label>
      <div className="form-two-columns">
        <label className="form-field"><span>Priority</span><select value={priority} onChange={(event) => setPriority(event.target.value as TaskPriority)}><option value="low">Low</option><option value="normal">Normal</option><option value="high">High</option><option value="urgent">Urgent</option></select></label>
        <label className="form-field"><span>Assign to</span><select value={assignedAgentId} onChange={(event) => setAssignedAgentId(event.target.value)}><option value="">Unassigned</option>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name} — {agent.role}</option>)}</select></label>
      </div>
      {error && <div className="form-error">{error}</div>}
      <div className="modal-footnote"><Clock3 size={14} />Tasks are saved as queued. AI execution is not active in this milestone.</div>
      <div className="modal-actions"><button type="button" className="secondary-button" onClick={onClose} disabled={saving}>Cancel</button><button type="submit" className="primary-button" disabled={saving}>{saving ? 'Saving...' : 'Save task'} <Plus size={15} /></button></div>
    </form>
  </div>
}

function EmployeeModal({ saving, onClose, onSubmit }: { saving: boolean; onClose: () => void; onSubmit: (input: AgentCreateInput) => Promise<string | null> }) {
  const [name, setName] = useState('')
  const [role, setRole] = useState('Software Engineer')
  const [department, setDepartment] = useState('Engineering')
  const [room, setRoom] = useState('Development Room')
  const [color, setColor] = useState('#8c9bc8')
  const [error, setError] = useState<string | null>(null)

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!name.trim()) { setError('Enter an employee name.'); return }
    const result = await onSubmit({ name: name.trim(), role: role.trim(), department, room, color })
    setError(result)
  }

  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !saving) onClose() }}>
    <form className="modal-card" onSubmit={(event) => void submit(event)}>
      <div className="modal-heading"><div><span className="modal-eyebrow">COMPANY DIRECTORY</span><h2>Add employee</h2><p>Create a persistent employee profile for your virtual company.</p></div><button type="button" className="icon-button modal-close" onClick={onClose} aria-label="Close"><X size={18} /></button></div>
      <label className="form-field"><span>Employee name <b>*</b></span><input autoFocus maxLength={48} value={name} onChange={(event) => setName(event.target.value)} placeholder="e.g. Kiran" required /></label>
      <label className="form-field"><span>Role</span><input maxLength={80} value={role} onChange={(event) => setRole(event.target.value)} required /></label>
      <div className="form-two-columns">
        <label className="form-field"><span>Department</span><select value={department} onChange={(event) => setDepartment(event.target.value)}><option>Management</option><option>Engineering</option><option>Design</option><option>Research</option><option>Quality & Testing</option><option>Operations</option><option>Marketing</option></select></label>
        <label className="form-field"><span>Office room</span><select value={room} onChange={(event) => setRoom(event.target.value)}><option>CEO Office</option><option>Development Room</option><option>Design Studio</option><option>Research Room</option><option>Testing Lab</option><option>Meeting Room</option><option>Reception</option></select></label>
      </div>
      <label className="form-field color-field"><span>Employee color</span><input type="color" value={color} onChange={(event) => setColor(event.target.value)} /></label>
      {error && <div className="form-error">{error}</div>}
      <div className="modal-footnote"><Users size={14} />New employees start as idle. Their chat behavior is guided by the role and department you selected.</div>
      <div className="modal-actions"><button type="button" className="secondary-button" onClick={onClose} disabled={saving}>Cancel</button><button type="submit" className="primary-button" disabled={saving}>{saving ? 'Saving...' : 'Add employee'} <UserPlus size={15} /></button></div>
    </form>
  </div>
}

export default App
