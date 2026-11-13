import type { Agent } from './types'

// Phase 1 preview data. These become API-backed employee records in Phase 2/3.
export const initialAgents: Agent[] = [
  {
    id: 'ceo',
    name: 'Atlas',
    role: 'AI Orchestrator',
    status: 'working',
    room: 'CEO Office',
    color: '#c5a46d',
    currentTask: 'Monitoring the company workspace',
  },
  {
    id: 'pm',
    name: 'Mira',
    role: 'Project Manager',
    status: 'working',
    room: 'Development Room',
    color: '#73a9a1',
    currentTask: 'Planning the next sprint',
  },
  {
    id: 'dev',
    name: 'Arin',
    role: 'Software Engineer',
    status: 'working',
    room: 'Development Room',
    color: '#8c9bc8',
    currentTask: 'Preparing the office interface',
  },
  {
    id: 'design',
    name: 'Nia',
    role: 'UI/UX Designer',
    status: 'idle',
    room: 'Design Studio',
    color: '#c28ca8',
    currentTask: 'Waiting for a design brief',
  },
  {
    id: 'research',
    name: 'Ira',
    role: 'Research Analyst',
    status: 'idle',
    room: 'Research Room',
    color: '#89a98b',
    currentTask: 'Waiting for a research brief',
  },
  {
    id: 'qa',
    name: 'Dev',
    role: 'QA Engineer',
    status: 'meeting',
    room: 'Meeting Room',
    color: '#d69a70',
    currentTask: 'Reviewing test strategy',
  },
]
