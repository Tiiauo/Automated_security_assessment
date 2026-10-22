import { request } from './client'
import type { VulnerabilitySummary } from './vulnerabilities'

export type AttackPathSummary = {
  id: number
  project_id: number
  run_id: number
  path_code: string
  path_title: string
  path_summary: string | null
  final_impact_text: string | null
  step_count: number
  vulns: VulnerabilitySummary[]
}

export type AttackPathStep = {
  step_order: number
  step_text: string | null
  vuln: VulnerabilitySummary
}

export type AttackPathDetail = AttackPathSummary & {
  steps: AttackPathStep[]
}

export type AttackPathList = {
  items: AttackPathSummary[]
  total: number
  page: number
  page_size: number
}

export const attackPathApi = {
  list: (projectId: number | string, query: { runId?: number | null; page?: number; pageSize?: number } = {}) => {
    const search = new URLSearchParams()
    if (query.runId) search.set('run_id', String(query.runId))
    search.set('page', String(query.page ?? 1))
    search.set('page_size', String(query.pageSize ?? 20))
    return request<AttackPathList>(`/api/projects/${projectId}/attack-paths?${search}`)
  },

  detail: (projectId: number | string, pathId: number | string) =>
    request<AttackPathDetail>(`/api/projects/${projectId}/attack-paths/${pathId}`),
}
