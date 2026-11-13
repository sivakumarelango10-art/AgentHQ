export type AgentStatus = 'working' | 'idle' | 'meeting' | 'offline'

export type Agent = {
  id: string
  name: string
  role: string
  department: string
  status: AgentStatus
  room: string
  color: string
  currentTask: string
}

export type ApiAgent = Omit<Agent, 'currentTask'> & { current_task: string }

export type TaskPriority = 'low' | 'normal' | 'high' | 'urgent'
export type TaskStatus = 'queued' | 'cancelled'

export type Task = {
  id: string
  title: string
  description: string
  priority: TaskPriority
  status: TaskStatus
  assigned_agent_id: string | null
  assigned_agent_name: string | null
  assigned_agent_role: string | null
  created_at: string
  updated_at: string
}

export type BackendHealth = {
  status: 'ok' | 'degraded'
  app: string
  database?: string
  ollama_connected: boolean
  model: string | null
}

export type AgentCreateInput = {
  name: string
  role: string
  department: string
  room: string
  color: string
}

export type TaskCreateInput = {
  title: string
  description: string
  priority: TaskPriority
  assigned_agent_id: string | null
}


export type Conversation = {
  id: string
  agent_id: string
  agent_name: string
  agent_role: string
  title: string
  created_at: string
  updated_at: string
}

export type ConversationMessage = {
  id: string
  conversation_id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
}

export type AgentChatResponse = {
  conversation_id: string
  agent: { id: string; name: string; role: string }
  user_message: ConversationMessage
  assistant_message: ConversationMessage
  model: string
  latency_ms: number
}
