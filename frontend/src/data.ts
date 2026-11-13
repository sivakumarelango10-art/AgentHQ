import type { Agent } from './types'

// Fallback records shown only until the local SQLite API responds.
export const initialAgents: Agent[] = [
  { id: 'ceo', name: 'Atlas', role: 'AI Orchestrator', department: 'Management', status: 'idle', room: 'CEO Office', color: '#c5a46d', currentTask: 'Available — awaiting assignment' },
  { id: 'pm', name: 'Mira', role: 'Project Manager', department: 'Management', status: 'idle', room: 'Development Room', color: '#73a9a1', currentTask: 'Available — awaiting assignment' },
  { id: 'dev', name: 'Arin', role: 'Software Engineer', department: 'Engineering', status: 'idle', room: 'Development Room', color: '#8c9bc8', currentTask: 'Available — awaiting assignment' },
  { id: 'design', name: 'Nia', role: 'UI/UX Designer', department: 'Design', status: 'idle', room: 'Design Studio', color: '#c28ca8', currentTask: 'Available — awaiting assignment' },
  { id: 'research', name: 'Ira', role: 'Research Analyst', department: 'Research', status: 'idle', room: 'Research Room', color: '#89a98b', currentTask: 'Available — awaiting assignment' },
  { id: 'qa', name: 'Dev', role: 'QA Engineer', department: 'Quality & Testing', status: 'idle', room: 'Meeting Room', color: '#d69a70', currentTask: 'Available — awaiting assignment' },
]
