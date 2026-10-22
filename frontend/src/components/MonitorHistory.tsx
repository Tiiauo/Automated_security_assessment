import { useEffect, useState } from 'react'
import { monitorApi } from '../api/monitor'
import { formatTime } from '../utils/format'
import { Icon } from './Icon'

export default function MonitorHistory({ projectId, runId }: { projectId: string; runId?: number | null }) {
  const [open, setOpen] = useState(false)
  const [kind, setKind] = useState('messages')
  const [role, setRole] = useState('')
  const [stage, setStage] = useState('')
  const [level, setLevel] = useState('')
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [rows, setRows] = useState<{ id: number; text: string; label: string; created_at: string }[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open) return
    let active = true
    setBusy(true)
    setError('')
    const request = kind === 'messages'
      ? monitorApi.messages(projectId, { runId, workerRole: role || undefined, page, pageSize: 20 }).then((data) => ({
        ...data, items: data.items.map((row) => ({ id: row.id, text: row.message_text, label: row.worker_role, created_at: row.created_at })),
      }))
      : monitorApi.logs(projectId, { runId, level: level || undefined, stageId: stage ? Number(stage) : null, page, pageSize: 20 }).then((data) => ({
        ...data, items: data.items.map((row) => ({ id: row.id, text: row.log_content, label: row.log_level, created_at: row.created_at })),
      }))
    void request.then((data) => {
      if (active) { setRows(data.items); setTotal(data.total) }
    }).catch((err: unknown) => {
      if (active) setError(err instanceof Error ? err.message : '历史记录加载失败')
    }).finally(() => { if (active) setBusy(false) })
    return () => { active = false }
  }, [open, projectId, runId, kind, role, stage, level, page])

  return (
    <details className="card history-card" onToggle={(event) => setOpen(event.currentTarget.open)} style={{ marginTop: 16 }}>
      <summary className="card-head history-summary">
        <Icon name="chevron-right" size={14} className="history-chevron" />
        <span className="card-title">历史消息与日志</span>
        <span className="field-help history-hint">{open ? '收起' : '展开'}</span>
      </summary>
      <div style={{ padding: 16 }}>
        <div className="log-toolbar" style={{ flexWrap: 'wrap', marginBottom: 12 }}>
          <select aria-label="历史记录类型" value={kind} onChange={(event) => { setKind(event.target.value); setPage(1) }}>
            <option value="messages">协作消息</option><option value="logs">运行日志</option>
          </select>
          {kind === 'messages' ? <select aria-label="角色筛选" value={role} onChange={(event) => { setRole(event.target.value); setPage(1) }}>
            <option value="">全部角色</option>
            {['orchestrator', 'env_inspector', 'code_analyst', 'vuln_verifier', 'report_writer', 'ops_assistant'].map((value) => <option key={value}>{value}</option>)}
          </select> : <>
            <select aria-label="日志级别" value={level} onChange={(event) => { setLevel(event.target.value); setPage(1) }}>
              <option value="">全部级别</option>{['debug', 'info', 'warning', 'error'].map((value) => <option key={value}>{value}</option>)}
            </select>
            <input aria-label="阶段编号" type="number" min="1" placeholder="阶段编号" value={stage} onChange={(event) => { setStage(event.target.value); setPage(1) }} />
          </>}
          <button type="button" className="btn btn-secondary btn-sm" disabled={page <= 1 || busy} onClick={() => setPage(page - 1)}>上一页</button>
          <span>{page} / {Math.max(1, Math.ceil(total / 20))} 页 · {total} 条</span>
          <button type="button" className="btn btn-secondary btn-sm" disabled={page * 20 >= total || busy} onClick={() => setPage(page + 1)}>下一页</button>
        </div>
        {error && <div role="alert" className="alert alert-error">{error}</div>}
        {busy ? <p>加载中…</p> : rows.map((row) => <div key={row.id} style={{ borderTop: '1px solid var(--border)', padding: '8px 0' }}>
          <small>{formatTime(row.created_at)} · {row.label}</small>
          <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{row.text}</pre>
        </div>)}
        {!busy && !error && rows.length === 0 && <p>暂无历史记录</p>}
      </div>
    </details>
  )
}
