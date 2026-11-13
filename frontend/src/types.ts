export type AgentStatus = 'working' | 'idle' | 'meeting' | 'offline'

export type Agent = {
  id: string
  name: string
  role: string
  status: AgentStatus
  room: string
  color: string
  currentTask: string
}

export type BackendHealth = {
  status: 'ok' | 'degraded'
  app: string
  ollama_connected: boolean
  model: string | null
}
