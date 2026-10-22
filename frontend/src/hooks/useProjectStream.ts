import { useEffect, useRef, useState } from 'react'
import { monitorApi } from '../api/monitor'
import { DEMO_MONITOR_SNAPSHOT, DEMO_RESOURCES } from '../api/demo'
import type {
  ChatMessage,
  MonitorSnapshot,
  ResourceUsage,
  RuntimeLog,
  StreamEvent,
  WorkerTask,
} from '../api/monitor'

export type StreamConnection = 'connecting' | 'connected' | 'reconnecting' | 'demo' | 'closed'

function nowTime(): string {
  return new Date().toLocaleTimeString('zh-CN', { hour12: false })
}

function appendCapped<T extends { id?: number }>(items: T[], next: T, cap: number): T[] {
  return [...items.filter((item) => !next.id || item.id !== next.id), next].slice(-cap)
}

const DEMO_ENABLED = import.meta.env.VITE_DEMO_MODE === '1'

export function useProjectStream(projectId: string | undefined, runId?: number | null) {
  const [snapshot, setSnapshot] = useState<MonitorSnapshot | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [logs, setLogs] = useState<RuntimeLog[]>([])
  const [resources, setResources] = useState<ResourceUsage[]>([])
  const [connection, setConnection] = useState<StreamConnection>('connecting')
  const [attempt, setAttempt] = useState(0)
  const [lastUpdate, setLastUpdate] = useState('')
  const [revision, setRevision] = useState(0)
  const socketRef = useRef<WebSocket | null>(null)
  const timerRef = useRef<number | null>(null)
  const closedRef = useRef(false)
  const attemptRef = useRef(0)
  const demoRef = useRef(false)

  useEffect(() => {
    if (!projectId) {
      setConnection('closed')
      return
    }

    closedRef.current = false
    demoRef.current = false
    attemptRef.current = 0
    setAttempt(0)
    setConnection('connecting')
    setSnapshot(null)
    setMessages([])
    setLogs([])
    setResources([])
    let snapshotVersion = 0

    const enterDemo = () => {
      demoRef.current = true
      const demoSnapshot = {
        ...DEMO_MONITOR_SNAPSHOT,
        stages: DEMO_MONITOR_SNAPSHOT.stages.map((stage) =>
          stage.stage_status === 'running'
            ? { ...stage, started_at: new Date(Date.now() - 22 * 60 * 1000).toISOString() }
            : stage,
        ),
      }
      setSnapshot(demoSnapshot)
      setMessages(demoSnapshot.recent_messages)
      setLogs(demoSnapshot.recent_logs)
      setResources(DEMO_RESOURCES)
      setLastUpdate(nowTime())
      setConnection('demo')
    }

    const connect = () => {
      if (closedRef.current) return
      const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const query = runId ? `?run_id=${runId}` : ''
      const url = `${protocol}://${window.location.host}/api/projects/${projectId}/stream${query}`
      let socket: WebSocket
      try {
        socket = new WebSocket(url)
      } catch {
        if (DEMO_ENABLED) enterDemo()
        else setConnection('reconnecting')
        return
      }
      socketRef.current = socket

      socket.onopen = () => {
        if (closedRef.current) {
          socket.close()
          return
        }
        attemptRef.current = 0
        setAttempt(0)
        setConnection('connected')
      }

      socket.onmessage = (event) => {
        if (closedRef.current || socketRef.current !== socket) return
        let message: StreamEvent
        try {
          message = JSON.parse(event.data as string) as StreamEvent
        } catch {
          return
        }
        if (message.type === 'ping') {
          socket.send(JSON.stringify({ type: 'pong', timestamp: new Date().toISOString() }))
          return
        }
        setLastUpdate(nowTime())
        const data = message.data ?? {}

        if (message.type === 'snapshot') {
          const version = ++snapshotVersion
          setRevision((previous) => previous + 1)
          const next = data as unknown as MonitorSnapshot
          setSnapshot(next)
          setMessages(next.recent_messages ?? [])
          setLogs(next.recent_logs ?? [])
          setResources(next.latest_resource ? [next.latest_resource] : [])
          void monitorApi.resources(projectId, message.run_id || runId).then((history) => {
            if (closedRef.current || socketRef.current !== socket || version !== snapshotVersion) return
            setResources((previous) => {
              const rows = new Map([...history.items, ...previous].map((item) => [item.id, item]))
              return [...rows.values()].sort((a, b) => a.recorded_at.localeCompare(b.recorded_at)).slice(-120)
            })
          }).catch(() => { /* The live sample remains available when history cannot be loaded. */ })
          return
        }

        if (message.type === 'project_status') {
          setSnapshot((previous) => previous ? { ...previous, project_status: data.project_status as MonitorSnapshot['project_status'] } : previous)
        }
        if (['project_status', 'vulnerability_found', 'stage_status', 'report_ready'].includes(message.type)) {
          setRevision((previous) => previous + 1)
          window.dispatchEvent(new CustomEvent('project-update', { detail: { projectId, runId: message.run_id, type: message.type } }))
        }

        if (message.type === 'stage_status') {
          const stageId = Number(data.stage_id ?? 0)
          setSnapshot((previous) => {
            if (!previous) return previous
            const stages = [...previous.stages]
            const index = stages.findIndex((item) => item.stage_id === stageId)
            const nextStage = {
              stage_id: stageId,
              stage_name: String(data.stage_name ?? ''),
              stage_status: String(data.stage_status ?? 'pending'),
              started_at: (data.started_at as string | null) ?? null,
              finished_at: (data.finished_at as string | null) ?? null,
              error_message: (data.error_message as string | null) ?? null,
            }
            if (index >= 0) stages[index] = { ...stages[index], ...nextStage }
            else stages.push(nextStage)
            return { ...previous, stages }
          })
          return
        }

        if (message.type === 'worker_status') {
          const workerId = Number(data.worker_task_id ?? 0)
          setSnapshot((previous) => {
            if (!previous) return previous
            const workers = [...previous.workers]
            const index = workers.findIndex((item) => item.id === workerId)
            if (index >= 0) {
              workers[index] = {
                ...workers[index],
                ...data,
                task_status: String(data.task_status ?? workers[index].task_status) as WorkerTask['task_status'],
                error_message: (data.error_message as string | null) ?? workers[index].error_message,
              }
            } else {
              workers.push({
                id: workerId,
                project_id: Number(message.project_id),
                run_id: Number(message.run_id),
                stage_id: Number(data.stage_id ?? 0),
                worker_role: String(data.worker_role ?? ''),
                task_content: String(data.task_content ?? ''),
                task_status: String(data.task_status ?? 'idle') as WorkerTask['task_status'],
                result_summary: (data.result_summary as string | null) ?? null,
                error_message: (data.error_message as string | null) ?? null,
                retry_count: Number(data.retry_count ?? 0),
                started_at: (data.started_at as string | null) ?? null,
                finished_at: (data.finished_at as string | null) ?? null,
              })
            }
            return { ...previous, workers }
          })
          return
        }

        if (message.type === 'chat_message') {
          setMessages((previous) => appendCapped(previous, data as unknown as ChatMessage, 200))
          return
        }

        if (message.type === 'runtime_log') {
          setLogs((previous) =>
            appendCapped(
              previous,
              {
                ...(data as unknown as RuntimeLog),
                project_id: Number(message.project_id),
                run_id: Number(message.run_id),
              },
              500,
            ),
          )
          return
        }

        if (message.type === 'resource_usage') {
          const resource = data as unknown as ResourceUsage
          setResources((previous) => appendCapped(previous, resource, 120))
          setSnapshot((previous) => (previous ? { ...previous, latest_resource: resource } : previous))
          return
        }

        if (message.type === 'vulnerability_found') {
          setSnapshot((previous) => {
            if (!previous || !data.vuln_counts) return previous
            return { ...previous, vuln_counts: data.vuln_counts as Record<string, number> }
          })
        }
      }

      socket.onerror = () => {
        socket.close()
      }

      socket.onclose = (event) => {
        if (socketRef.current !== socket) return
        socketRef.current = null
        if (closedRef.current || demoRef.current) return
        if ([4400, 4401, 4403, 4404, 1008].includes(event.code)) {
          if (event.code === 4401) window.dispatchEvent(new Event('auth:unauthorized'))
          setConnection('closed')
          return
        }
        if (DEMO_ENABLED && attemptRef.current === 0) {
          enterDemo()
          return
        }
        if (DEMO_ENABLED && attemptRef.current >= 1) {
          enterDemo()
          return
        }
        attemptRef.current += 1
        setAttempt(attemptRef.current)
        setConnection('reconnecting')
        const delay = Math.min(30_000, 1_000 * 2 ** (attemptRef.current - 1))
        timerRef.current = window.setTimeout(connect, delay)
      }
    }

    connect()

    return () => {
      closedRef.current = true
      if (timerRef.current !== null) window.clearTimeout(timerRef.current)
      socketRef.current?.close()
      socketRef.current = null
    }
  }, [projectId, runId])

  return { snapshot, messages, logs, resources, connection, attempt, lastUpdate, revision }
}
