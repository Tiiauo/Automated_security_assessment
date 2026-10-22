import { request } from './client'

export type SandboxItem = {
  sandbox_id: string
  project_id: number
  project_name: string
  status: string
  created_at: string | null
}

export type CleanupProject = {
  project_id: number
  project_name: string
  cleanup_error: string | null
  updated_at: string | null
}

export type SandboxList = {
  items: SandboxItem[]
  cleanup_pending: CleanupProject[]
}

export type SystemResourceSummary = {
  running_projects: number
  cpu_usage: number
  memory_usage: number
  token_count: number
  projects: {
    project_id: number
    project_name: string
    cpu_usage: number
    memory_usage: number
    token_count: number
  }[]
}

export type SystemLog = {
  id: number
  log_level: string
  log_content: string
  source: string | null
  created_at: string | null
}

export type SystemLogList = {
  items: SystemLog[]
  total: number
  page: number
  page_size: number
}

export const adminApi = {
  sandboxes: () => request<SandboxList>('/api/system/sandboxes'),

  destroySandbox: (sandboxId: string) =>
    request<{ cleaned: boolean }>(`/api/system/sandboxes/${encodeURIComponent(sandboxId)}`, {
      method: 'DELETE',
    }),

  resources: (params: { startTime?: string; endTime?: string } = {}) => {
    const search = new URLSearchParams()
    if (params.startTime) search.set('start_time', params.startTime)
    if (params.endTime) search.set('end_time', params.endTime)
    return request<SystemResourceSummary>(`/api/system/resources?${search}`)
  },

  logs: (params: { page?: number; pageSize?: number; level?: string; keyword?: string } = {}) => {
    const search = new URLSearchParams()
    search.set('page', String(params.page ?? 1))
    search.set('page_size', String(params.pageSize ?? 20))
    if (params.level) search.set('level', params.level)
    if (params.keyword) search.set('keyword', params.keyword)
    return request<SystemLogList>(`/api/system/logs?${search}`)
  },
}
