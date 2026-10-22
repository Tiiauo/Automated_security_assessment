import { request } from './client'

export type RiskLevel = 'critical' | 'high' | 'medium' | 'low' | 'info'
export type VerifyStatus = 'pending' | 'verified' | 'unverified' | 'false_positive'

export type VulnerabilitySummary = {
  id: number
  project_id: number
  run_id: number
  stage_id: number | null
  vuln_code: string
  vuln_title: string
  risk_level: RiskLevel
  cvss_score: string | number | null
  file_path: string | null
  verify_status: VerifyStatus
  created_at: string | null
  updated_at: string | null
}

export type VulnerabilityDetail = VulnerabilitySummary & {
  impact_text: string | null
  condition_text: string | null
  evidence_text: string | null
  reproduce_steps_text: string | null
  verify_code_text: string | null
}

export type VulnerabilityList = {
  items: VulnerabilitySummary[]
  total: number
  page: number
  page_size: number
}

export type VulnerabilityQuery = {
  runId?: number | null
  riskLevel?: RiskLevel | ''
  verifyStatus?: VerifyStatus | ''
  keyword?: string
  page?: number
  pageSize?: number
}

export const vulnerabilityApi = {
  list: (projectId: number | string, query: VulnerabilityQuery = {}) => {
    const search = new URLSearchParams()
    if (query.runId) search.set('run_id', String(query.runId))
    if (query.riskLevel) search.set('risk_level', query.riskLevel)
    if (query.verifyStatus) search.set('verify_status', query.verifyStatus)
    if (query.keyword) search.set('keyword', query.keyword)
    search.set('page', String(query.page ?? 1))
    search.set('page_size', String(query.pageSize ?? 20))
    return request<VulnerabilityList>(`/api/projects/${projectId}/vulnerabilities?${search}`)
  },

  detail: (projectId: number | string, vulnId: number | string) =>
    request<VulnerabilityDetail>(`/api/projects/${projectId}/vulnerabilities/${vulnId}`),
}
