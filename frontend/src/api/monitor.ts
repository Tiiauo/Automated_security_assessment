import { request } from './client'
import type { ProjectStatus } from './projects'

export type WorkerStatus = 'idle' | 'running' | 'success' | 'failed'
export type MessageType = 'info' | 'tool_call' | 'result' | 'warning' | 'error'
export type LogLevel = 'debug' | 'info' | 'warning' | 'error'

export type WorkerTask = {
  id: number
  project_id: number
  run_id: number
  stage_id: number
  worker_role: string
  task_content: string
  task_status: WorkerStatus
  result_summary: string | null
  error_message: string | null
  retry_count: number
  started_at: string | null
  finished_at: string | null
}

export type ChatMessage = {
  id: number
  worker_role: string
  message_type: MessageType
  message_text: string
  created_at: string
}

export type RuntimeLog = {
  id: number
  project_id: number | null
  run_id: number | null
  stage_id: number | null
  worker_task_id: number | null
  log_level: LogLevel
  log_content: string
  created_at: string
}

export type ResourceUsage = {
  id?: number
  cpu_usage: string | number
  memory_usage: number
  token_count: number
  recorded_at: string
}

export type MonitorSnapshot = {
  project_status: ProjectStatus
  current_run_id: number
  selected_run_id?: number
  stages: {
    stage_id: number
    stage_name: string
    stage_status: string
    started_at: string | null
    finished_at: string | null
    error_message: string | null
  }[]
  workers: WorkerTask[]
  recent_messages: ChatMessage[]
  recent_logs: RuntimeLog[]
  latest_resource: ResourceUsage | null
  vuln_counts: Record<string, number>
}

export type StreamEvent = {
  type: string
  project_id: number
  run_id: number
  timestamp: string
  data: Record<string, unknown>
}

type Paged<T> = { items: T[]; total: number; page: number; page_size: number }

export const monitorApi = {
  workers: (projectId: number | string, runId?: number | null, stageId?: number | null) => {
    const search = new URLSearchParams()
    if (runId) search.set('run_id', String(runId))
    if (stageId) search.set('stage_id', String(stageId))
    return request<Paged<WorkerTask>>(`/api/projects/${projectId}/workers?${search}`)
  },

  messages: (
    projectId: number | string,
    query: { runId?: number | null; workerRole?: string; messageType?: string; page?: number; pageSize?: number } = {},
  ) => {
    const search = new URLSearchParams()
    if (query.runId) search.set('run_id', String(query.runId))
    if (query.workerRole) search.set('worker_role', query.workerRole)
    if (query.messageType) search.set('message_type', query.messageType)
    search.set('page', String(query.page ?? 1))
    search.set('page_size', String(query.pageSize ?? 50))
    return request<Paged<ChatMessage>>(`/api/projects/${projectId}/messages?${search}`)
  },

  logs: (
    projectId: number | string,
    query: { runId?: number | null; level?: string; stageId?: number | null; page?: number; pageSize?: number } = {},
  ) => {
    const search = new URLSearchParams()
    if (query.runId) search.set('run_id', String(query.runId))
    if (query.level) search.set('level', query.level)
    if (query.stageId) search.set('stage_id', String(query.stageId))
    search.set('page', String(query.page ?? 1))
    search.set('page_size', String(query.pageSize ?? 100))
    return request<Paged<RuntimeLog>>(`/api/projects/${projectId}/logs?${search}`)
  },

  resources: (projectId: number | string, runId?: number | null) => {
    const search = new URLSearchParams()
    if (runId) search.set('run_id', String(runId))
    search.set('page', '1')
    search.set('page_size', '120')
    return request<Paged<ResourceUsage>>(`/api/projects/${projectId}/resources?${search}`)
  },
}
