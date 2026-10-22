import { request } from './client'

export type ReportData = {
  report_id: number
  project_id: number
  run_id: number
  report_markdown: string
  report_html: string
  report_file_path: string
  created_at: string | null
}

export const reportApi = {
  get: (projectId: number | string, runId?: number | null) => {
    const search = new URLSearchParams()
    if (runId) search.set('run_id', String(runId))
    search.set('format', 'json')
    return request<ReportData>(`/api/projects/${projectId}/report?${search}`)
  },

  downloadUrl: (projectId: number | string, runId: number | null | undefined, format: 'md' | 'html') => {
    const search = new URLSearchParams()
    if (runId) search.set('run_id', String(runId))
    search.set('format', format)
    return `/api/projects/${projectId}/report/download?${search}`
  },
}
