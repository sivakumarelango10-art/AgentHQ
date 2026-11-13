import { useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties, FormEvent } from 'react'
import { Bot, Clock3, MessageCircle, Plus, Send, Sparkles, UserRound, Wifi, X } from 'lucide-react'
import { getConversationMessages, getConversations, sendAgentMessage } from '../../api'
import type { Agent, Conversation, ConversationMessage } from '../../types'

type Props = { agents: Agent[] }

const starterPrompts = [
  'Introduce yourself and explain how you can help the company.',
  'Help me plan the next steps for AgentHQ.',
  'What information do you need before starting a task?',
]

function formatTime(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export function ConversationsView({ agents }: Props) {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null)
  const [activeAgentId, setActiveAgentId] = useState(agents[0]?.id ?? '')
  const [messages, setMessages] = useState<ConversationMessage[]>([])
  const [draft, setDraft] = useState('')
  const [loadingConversations, setLoadingConversations] = useState(true)
  const [loadingMessages, setLoadingMessages] = useState(false)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  const activeAgent = useMemo(
    () => agents.find((agent) => agent.id === activeAgentId) ?? agents[0],
    [agents, activeAgentId],
  )

  useEffect(() => {
    if (!agents.length) return
    if (!agents.some((agent) => agent.id === activeAgentId)) setActiveAgentId(agents[0].id)
  }, [agents, activeAgentId])

  useEffect(() => {
    let active = true
    setLoadingConversations(true)
    getConversations()
      .then((items) => { if (active) setConversations(items) })
      .catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : 'Could not load conversations.') })
      .finally(() => { if (active) setLoadingConversations(false) })
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!activeConversationId) {
      setMessages([])
      return
    }
    let active = true
    setLoadingMessages(true)
    getConversationMessages(activeConversationId)
      .then((result) => {
        if (!active) return
        setMessages(result.items)
        setActiveAgentId(result.conversation.agent_id)
        setError(null)
      })
      .catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : 'Could not load this conversation.') })
      .finally(() => { if (active) setLoadingMessages(false) })
    return () => { active = false }
  }, [activeConversationId])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, sending])

  const startNewConversation = (agentId = activeAgentId) => {
    setActiveAgentId(agentId)
    setActiveConversationId(null)
    setMessages([])
    setDraft('')
    setError(null)
    setNotice(null)
  }

  const openConversation = (conversation: Conversation) => {
    setActiveAgentId(conversation.agent_id)
    setActiveConversationId(conversation.id)
    setError(null)
    setNotice(null)
  }

  const handleSend = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const message = draft.trim()
    if (!message || !activeAgent || sending) return
    setSending(true)
    setError(null)
    setNotice(null)
    setDraft('')
    const pendingId = 'pending-' + Date.now()
    const pendingMessage: ConversationMessage = {
      id: pendingId,
      conversation_id: activeConversationId ?? 'pending',
      role: 'user',
      content: message,
      created_at: new Date().toISOString(),
    }
    setMessages((current) => [...current, pendingMessage])
    try {
      const result = await sendAgentMessage(activeAgent.id, message, activeConversationId)
      setActiveConversationId(result.conversation_id)
      setMessages((current) => [
        ...current.filter((item) => item.id !== pendingId),
        result.user_message,
        result.assistant_message,
      ])
      const updated = await getConversations()
      setConversations(updated)
      setNotice(result.agent.name + ' replied using ' + result.model + ' in ' + (result.latency_ms / 1000).toFixed(1) + 's.')
    } catch (cause) {
      setMessages((current) => current.filter((item) => item.id !== pendingId))
      setDraft(message)
      setError(cause instanceof Error ? cause.message : 'The local AI employee could not respond.')
    } finally {
      setSending(false)
    }
  }

  return (
    <section className="management-view conversations-view">
      <div className="page-heading">
        <div>
          <div className="eyebrow"><span className="eyebrow-line" /> LOCAL AI WORKSPACE</div>
          <h1>Conversations</h1>
          <p>Talk directly with your AI employees. Each employee responds using their own role and conversation history.</p>
        </div>
        <button className="primary-button" onClick={() => startNewConversation()} disabled={!agents.length}>
          <Plus size={16} /> New conversation
        </button>
      </div>

      <div className="conversation-layout">
        <aside className="conversation-sidebar">
          <div className="conversation-sidebar-section">
            <div className="conversation-section-heading">
              <span>YOUR AI TEAM</span>
              <span>{agents.length}</span>
            </div>
            <div className="conversation-agent-list">
              {agents.map((agent) => (
                <button
                  key={agent.id}
                  className={'conversation-agent ' + (activeAgentId === agent.id && !activeConversationId ? 'selected' : '')}
                  onClick={() => startNewConversation(agent.id)}
                >
                  <span className="agent-avatar" style={{ '--agent-color': agent.color } as CSSProperties}>{agent.name.slice(0, 1)}</span>
                  <span className="conversation-agent-copy"><strong>{agent.name}</strong><small>{agent.role}</small></span>
                  <span className={'status-dot status-' + agent.status} title={agent.status} />
                </button>
              ))}
            </div>
          </div>
          <div className="conversation-sidebar-section conversation-history-section">
            <div className="conversation-section-heading"><span>RECENT CHATS</span><span>{conversations.length}</span></div>
            {loadingConversations ? (
              <div className="conversation-sidebar-empty">Loading conversations…</div>
            ) : conversations.length === 0 ? (
              <div className="conversation-sidebar-empty">Your conversations will appear here.</div>
            ) : (
              <div className="conversation-history-list">
                {conversations.map((conversation) => (
                  <button
                    key={conversation.id}
                    className={'conversation-history-item ' + (activeConversationId === conversation.id ? 'selected' : '')}
                    onClick={() => openConversation(conversation)}
                  >
                    <MessageCircle size={15} />
                    <span><strong>{conversation.title}</strong><small>{conversation.agent_name} · {formatTime(conversation.updated_at)}</small></span>
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="conversation-local-note"><Wifi size={14} /><span>Private local conversations · Ollama</span></div>
        </aside>

        <div className="conversation-main">
          {activeAgent ? (
            <>
              <header className="conversation-header">
                <div className="conversation-agent-heading">
                  <span className="agent-avatar conversation-large-avatar" style={{ '--agent-color': activeAgent.color } as CSSProperties}>{activeAgent.name.slice(0, 1)}</span>
                  <span><strong>{activeAgent.name}</strong><small>{activeAgent.role} · {activeAgent.department}</small></span>
                </div>
                <div className="conversation-model-pill"><span className="live-dot" /> Qwen3 · Local AI</div>
              </header>

              <div className="conversation-messages">
                {loadingMessages ? (
                  <div className="conversation-loading">Loading conversation…</div>
                ) : messages.length === 0 ? (
                  <div className="conversation-welcome">
                    <div className="conversation-welcome-icon"><Sparkles size={23} /></div>
                    <span className="conversation-welcome-kicker">AGENTHQ EMPLOYEE CHAT</span>
                    <h2>Talk to {activeAgent.name}</h2>
                    <p>{activeAgent.name} is your {activeAgent.role.toLowerCase()}. Start a conversation, ask for advice, or work through an idea together.</p>
                    <div className="conversation-starters">
                      {starterPrompts.map((prompt) => (
                        <button key={prompt} onClick={() => setDraft(prompt)}>{prompt}</button>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="conversation-message-list">
                    {messages.map((message) => (
                      <article key={message.id} className={'chat-message ' + message.role}>
                        <span className={'chat-message-avatar ' + message.role}>
                          {message.role === 'assistant' ? <Bot size={16} /> : <UserRound size={16} />}
                        </span>
                        <div className="chat-message-content">
                          <div className="chat-message-meta">
                            <strong>{message.role === 'assistant' ? activeAgent.name : 'You'}</strong>
                            <time>{formatTime(message.created_at)}</time>
                          </div>
                          <div className="chat-message-text">{message.content}</div>
                        </div>
                      </article>
                    ))}
                    {sending && (
                      <article className="chat-message assistant">
                        <span className="chat-message-avatar assistant"><Bot size={16} /></span>
                        <div className="chat-message-content">
                          <div className="chat-message-meta"><strong>{activeAgent.name}</strong><span>Thinking with Qwen3…</span></div>
                          <div className="chat-thinking"><i /><i /><i /></div>
                        </div>
                      </article>
                    )}
                    <div ref={bottomRef} />
                  </div>
                )}
              </div>

              {notice && <div className="conversation-notice"><Clock3 size={14} />{notice}<button onClick={() => setNotice(null)} aria-label="Dismiss"><X size={13} /></button></div>}
              {error && <div className="conversation-error" role="alert">{error}</div>}
              <form className="conversation-composer" onSubmit={(event) => void handleSend(event)}>
                <textarea
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && !event.shiftKey) {
                      event.preventDefault()
                      event.currentTarget.form?.requestSubmit()
                    }
                  }}
                  placeholder={'Message ' + activeAgent.name + '…'}
                  rows={2}
                  maxLength={4000}
                  disabled={sending}
                />
                <div className="conversation-composer-footer">
                  <span>Enter to send · Shift + Enter for a new line · Responses run locally</span>
                  <button className="primary-button" type="submit" disabled={!draft.trim() || sending}>
                    <Send size={15} /> {sending ? 'Thinking…' : 'Send'}
                  </button>
                </div>
              </form>
              <div className="conversation-safety-note">AI employees can discuss and draft ideas in this milestone. They cannot yet execute tasks or access your files.</div>
            </>
          ) : (
            <div className="empty-state"><h3>No employees available</h3><p>Add an employee before starting a conversation.</p></div>
          )}
        </div>
      </div>
    </section>
  )
}
