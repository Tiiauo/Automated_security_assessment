import { request } from './client'

export type ProjectStatus = 'created' | 'running' | 'completed' | 'failed' | 'stopped'
export type SourceType = 'local_path' | 'git_repo'

export type Project = {
  id: number
  project_name: string
  source_type: SourceType
  source_path: string
  task_content: string
  project_status: ProjectStatus
  sandbox_type: string
  sandbox_id: string | null
  current_run_id: number
  last_started_at: string | null
  last_finished_at: string | null
  cleanup_pending: boolean
  created_by: number
  created_at: string | null
  updated_at: string | null
}

export type ProjectRun = {
  run_id: number
  source_revision: string | null
  source_fingerprint: string | null
  source_fingerprint_after: string | null
  created_at: string | null
}

export type StageItem = {
  stage_id: number
  stage_name: string
  stage_status: string
  started_at: string | null
  finished_at: string | null
  error_message: string | null
}

export type ProjectDetail = Project & {
  selected_run_id: number
  runs: ProjectRun[]
  stages: StageItem[]
  counts: { vulnerabilities: number; attack_paths: number; reports: number }
  report_status: 'ready' | 'pending' | 'none'
  vulnerability_stats?: { risk_levels: Record<string, number>; verify_statuses: Record<string, number> }
}

export type ProjectList = {
  items: Project[]
  total: number
  page: number
  page_size: number
}

export type CreateProjectPayload = {
  project_name: string
  source_type: SourceType
  source_path: string
  task_content: string
  sandbox_type: 'docker'
}

export const projectApi = {
  list: (params: {
    status?: ProjectStatus | ''
    keyword?: string
    page?: number
    pageSize?: number
  }) => {
    const search = new URLSearchParams()
    if (params.status) search.set('status', params.status)
    if (params.keyword) search.set('keyword', params.keyword)
    search.set('page', String(params.page ?? 1))
    search.set('page_size', String(params.pageSize ?? 20))
    return request<ProjectList>(`/api/projects?${search.toString()}`)
  },

  create: (payload: CreateProjectPayload) =>
    request<{ project_id: number; project_status: ProjectStatus }>('/api/projects', {
      method: 'POST',
      body: payload,
    }),

  detail: (projectId: number | string, runId?: number | null) =>
    request<ProjectDetail>(
      `/api/projects/${projectId}${runId ? `?run_id=${runId}` : ''}`,
    ),

  start: (projectId: number) =>
    request<{ project_status: ProjectStatus; run_id: number; sandbox_id: string | null }>(
      `/api/projects/${projectId}/start`,
      { method: 'POST' },
    ),

  stop: (projectId: number) =>
    request<{ project_status: ProjectStatus }>(`/api/projects/${projectId}/stop`, {
      method: 'POST',
    }),

  remove: (projectId: number) =>
    request<{ deleted: boolean; dirs_cleaned: boolean }>(`/api/projects/${projectId}`, {
      method: 'DELETE',
    }),
}
