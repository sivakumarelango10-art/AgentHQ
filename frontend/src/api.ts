import type { Agent, AgentChatResponse, AgentCreateInput, ApiAgent, BackendHealth, Conversation, ConversationMessage, Task, TaskCreateInput } from './types'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000'

async function request<T>(path: string, init?: RequestInit, timeoutMs = 8000): Promise<T> {
  const headers = new Headers(init?.headers)
  if (!headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
    signal: init?.signal ?? AbortSignal.timeout(timeoutMs),
  })

  if (!response.ok) {
    let message = `Request failed (${response.status})`
    try {
      const payload: unknown = await response.json()
      if (payload && typeof payload === 'object') {
        const record = payload as Record<string, unknown>
        const detail = record.detail
        if (typeof detail === 'string' && detail.trim()) {
          message = detail.trim()
        } else if (Array.isArray(detail)) {
          const messages = detail
            .map((item) => {
              if (!item || typeof item !== 'object') return String(item)
              const entry = item as Record<string, unknown>
              const location = Array.isArray(entry.loc) ? entry.loc.filter((part) => typeof part === 'string' || typeof part === 'number').join('.') : ''
              const text = typeof entry.msg === 'string' ? entry.msg : ''
              return [location, text].filter(Boolean).join(': ')
            })
            .filter(Boolean)
          if (messages.length) message = messages.join('; ')
        } else if (detail && typeof detail === 'object') {
          const detailRecord = detail as Record<string, unknown>
          if (typeof detailRecord.message === 'string') {
            message = detailRecord.message
          } else {
            message = JSON.stringify(detail)
          }
        } else if (typeof record.message === 'string' && record.message.trim()) {
          message = record.message.trim()
        }
      }
    } catch {
      // Keep the HTTP fallback message when the response is not JSON.
    }
    throw new Error(message)
  }
  return response.json() as Promise<T>
}

export async function getHealth() {
  return request<BackendHealth>('/api/health')
}

export async function getAgents(): Promise<Agent[]> {
  const payload = await request<{ items: ApiAgent[] }>('/api/agents')
  return payload.items.map(({ current_task, ...agent }) => ({ ...agent, currentTask: current_task }))
}

export async function addAgent(input: AgentCreateInput): Promise<Agent> {
  const payload = await request<{ item: ApiAgent }>('/api/agents', {
    method: 'POST',
    body: JSON.stringify(input),
  })
  const { current_task, ...agent } = payload.item
  return { ...agent, currentTask: current_task }
}

export async function getTasks(): Promise<Task[]> {
  const payload = await request<{ items: Task[] }>('/api/tasks')
  return payload.items
}

export async function addTask(input: TaskCreateInput): Promise<Task> {
  const payload = await request<{ item: Task }>('/api/tasks', {
    method: 'POST',
    body: JSON.stringify(input),
  })
  return payload.item
}

export async function cancelTask(taskId: string): Promise<Task> {
  const payload = await request<{ item: Task }>(`/api/tasks/${encodeURIComponent(taskId)}/cancel`, { method: 'PATCH' })
  return payload.item
}



export async function getConversations(): Promise<Conversation[]> {
  const payload = await request<{ items: Conversation[] }>('/api/conversations')
  return payload.items
}

export async function getConversationMessages(conversationId: string): Promise<{
  conversation: Conversation
  items: ConversationMessage[]
}> {
  return request<{ conversation: Conversation; items: ConversationMessage[] }>('/api/conversations/' + encodeURIComponent(conversationId) + '/messages')
}

export async function sendAgentMessage(
  agentId: string,
  message: string,
  conversationId: string | null,
): Promise<AgentChatResponse> {
  return request<AgentChatResponse>(
    '/api/agents/' + encodeURIComponent(agentId) + '/chat',
    {
      method: 'POST',
      body: JSON.stringify({ message, conversation_id: conversationId }),
    },
    180000,
  )
}
