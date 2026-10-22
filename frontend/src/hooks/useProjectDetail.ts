import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../api/client'
import { projectApi } from '../api/projects'
import type { ProjectDetail } from '../api/projects'

export function useProjectDetail(id: string | undefined, runId?: number | null) {
  const [detail, setDetail] = useState<ProjectDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const requestId = useRef(0)

  const load = useCallback(async () => {
    if (!id) return
    const current = ++requestId.current
    setLoading(true)
    setError('')
    try {
      const next = await projectApi.detail(id, runId)
      if (current === requestId.current) setDetail(next)
    } catch (err) {
      if (current === requestId.current) setError(err instanceof ApiError ? err.message : '网络异常，请稍后重试')
    } finally {
      if (current === requestId.current) setLoading(false)
    }
  }, [id, runId])

  useEffect(() => {
    void load()
    return () => { requestId.current += 1 }
  }, [load])

  useEffect(() => {
    const update = (event: Event) => {
      const change = (event as CustomEvent<{ projectId: string; runId: number }>).detail
      if (change.projectId === id && (!runId || change.runId === runId)) void load()
    }
    window.addEventListener('project-update', update)
    return () => window.removeEventListener('project-update', update)
  }, [id, runId, load])

  return { detail, loading, error, reload: load }
}
