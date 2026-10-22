import { useEffect, useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import type { MessageType, WorkerTask } from '../api/monitor'
import { Icon } from '../components/Icon'
import type { IconName } from '../components/Icon'
import ProjectHeader from '../components/ProjectHeader'
import MonitorHistory from '../components/MonitorHistory'
import RuntimeLogList from '../components/RuntimeLogList'
import { DemoPill, EmptyState, LoadingBlock, WorkerStatusText } from '../components/ui'
import { useProjectDetail } from '../hooks/useProjectDetail'
import { useProjectStream } from '../hooks/useProjectStream'
import { formatClock } from '../utils/format'

const STAGE_ORDER = ['environment_scan', 'code_analysis', 'vulnerability_verify', 'report_generate', 'done']

const STAGE_LABELS: Record<string, string> = {
  environment_scan: '环境检查',
  code_analysis: '代码分析',
  vulnerability_verify: '漏洞验证',
  report_generate: '报告生成',
  done: '收尾',
}

const ROLE_META: Record<string, { label: string; icon: IconName; color: string; background: string }> = {
  orchestrator: { label: '通用处理', icon: 'workflow', color: 'var(--primary)', background: 'var(--primary-soft)' },
  env_inspector: { label: '环境检查', icon: 'scan-search', color: 'var(--success)', background: 'var(--success-soft)' },
  code_analyst: { label: '代码分析', icon: 'file-code', color: 'var(--high)', background: 'var(--high-soft)' },
  vuln_verifier: { label: '漏洞验证', icon: 'shield-alert', color: 'var(--danger)', background: 'var(--danger-soft)' },
  report_writer: { label: '报告整理', icon: 'file-text', color: 'var(--neutral)', background: 'var(--neutral-soft)' },
  ops_assistant: { label: '运维辅助', icon: 'activity', color: 'var(--success)', background: 'var(--success-soft)' },
}

const ROLE_ORDER = ['orchestrator', 'env_inspector', 'code_analyst', 'vuln_verifier', 'report_writer', 'ops_assistant']

const MESSAGE_META: Record<MessageType, { label: string; color: string; background: string }> = {
  info: { label: '普通消息', color: 'var(--primary)', background: 'var(--primary-soft)' },
  tool_call: { label: '工具调用', color: 'var(--warning)', background: 'var(--warning-soft)' },
  result: { label: '结果', color: 'var(--success)', background: 'var(--success-soft)' },
  warning: { label: '告警', color: 'var(--warning)', background: 'var(--warning-soft)' },
  error: { label: '错误', color: 'var(--danger)', background: 'var(--danger-soft)' },
}

type ChatFilter = 'all' | MessageType

function elapsedText(startedAt: string | null, finishedAt: string | null, now: number): string {
  if (!startedAt) return '—'
  const start = new Date(startedAt).getTime()
  const end = finishedAt ? new Date(finishedAt).getTime() : now
  const total = Math.max(0, Math.round((end - start) / 1000))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

function sparkHeights(values: number[]): number[] {
  const max = Math.max(...values, 1)
  return values.map((value) => Math.max(4, Math.round((value / max) * 32)))
}

function WorkerDesc({ worker }: { worker: WorkerTask | undefined }) {
  if (!worker) return <span className="role-desc">等待任务</span>
  return (
    <span className="role-desc" title={worker.result_summary || worker.error_message || worker.task_content}>
      {worker.result_summary || worker.error_message || worker.task_content || '等待任务'}
    </span>
  )
}

export default function MonitorPage() {
  const { id } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const runParam = searchParams.get('run_id')
  const parsedRun = runParam ? Number(runParam) : null
  const runId = parsedRun !== null && Number.isFinite(parsedRun) ? parsedRun : null
  const { detail, loading, error: detailError } = useProjectDetail(id, runId)
  const { snapshot, messages, logs, resources, connection, attempt, lastUpdate } = useProjectStream(id, runId)
  const [chatFilter, setChatFilter] = useState<ChatFilter>('all')
  const [roleFilter, setRoleFilter] = useState('')
  const [stageFilter, setStageFilter] = useState('')
  const [levels, setLevels] = useState<Set<string>>(new Set(['debug', 'info', 'warning', 'error']))
  const [paused, setPaused] = useState(false)
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])


  const currentStage = useMemo(() => {
    if (!snapshot) return undefined
    return (
      snapshot.stages.find((stage) => stage.stage_status === 'running') ??
      [...snapshot.stages].reverse().find((stage) => stage.started_at) ??
      snapshot.stages[0]
    )
  }, [snapshot])

  const currentStageIndex = currentStage ? Math.max(1, STAGE_ORDER.indexOf(currentStage.stage_name) + 1) : 0
  const currentStageProgress = currentStage ? (currentStageIndex / STAGE_ORDER.length) * 100 : 0

  const filteredMessages = useMemo(
    () => messages.filter((item) => (chatFilter === 'all' || item.message_type === chatFilter) && (!roleFilter || item.worker_role === roleFilter)),
    [messages, chatFilter, roleFilter],
  )

  const filteredLogs = useMemo(
    () =>
      logs.filter((log) => {
        if (!levels.has(log.log_level)) return false
        if (stageFilter && log.stage_id !== Number(stageFilter)) return false
        if (roleFilter && !snapshot?.workers.some((worker) => worker.id === log.worker_task_id && worker.worker_role === roleFilter)) return false
        return true
      }),
    [logs, levels, stageFilter, roleFilter, snapshot?.workers],
  )

  const latest = snapshot?.latest_resource ?? resources[resources.length - 1] ?? null
  const cpu = latest ? Number(latest.cpu_usage) || 0 : 0
  const memory = latest?.memory_usage ?? 0
  const token = latest?.token_count ?? 0
  const cpuSeries = resources.slice(-16).map((item) => Number(item.cpu_usage) || 0)
  const memorySeries = resources.slice(-16).map((item) => item.memory_usage)
  const tokenSeries = resources.slice(-16).map((item) => item.token_count)
  const previousToken = resources.length > 1 ? resources[resources.length - 2].token_count : token
  const tokenDelta = token - previousToken
  const vulnTotal = snapshot ? Object.values(snapshot.vuln_counts).reduce((sum, value) => sum + value, 0) : detail?.counts.vulnerabilities ?? 0

  if (loading && !detail && !snapshot) {
    return (
      <main className="page-pad">
        <LoadingBlock text="正在加载项目与实时监控数据…" />
      </main>
    )
  }

  if (!detail) {
    return (
      <main className="page-pad">
        <div className="alert alert-error">
          <Icon name="triangle-alert" size={14} />
          <span>{detailError || '项目不存在'}</span>
        </div>
        <Link className="btn btn-secondary" to="/projects">
          <Icon name="arrow-left" size={14} />
          返回项目列表
        </Link>
      </main>
    )
  }

  const connectionClass =
    connection === 'connected' || connection === 'demo'
      ? connection === 'demo'
        ? 'primary'
        : 'success'
      : connection === 'reconnecting' || connection === 'connecting'
        ? 'primary'
        : 'warning'

  const connectionText =
    connection === 'connected'
      ? 'WebSocket 已连接 · 实时同步中'
      : connection === 'demo'
        ? '演示模式 · 未连接后端实时通道'
        : connection === 'reconnecting'
          ? '连接已断开，正在自动重连…'
          : connection === 'connecting'
            ? '正在连接实时通道…'
            : '实时通道未连接'

  const connectionRight =
    connection === 'connected'
      ? `自动重连已开启（指数退避，上限 30s）· 最后更新 ${lastUpdate || '—'}`
      : connection === 'demo'
        ? '展示原型演示数据 · 后端 WebSocket 接入后自动切换'
        : connection === 'reconnecting'
          ? `第 ${attempt} 次重试 · 页面状态已保留`
          : `最后更新 ${lastUpdate || '—'}`

  const changeRun = (next: number) => {
    const nextParams = new URLSearchParams(searchParams)
    nextParams.set('run_id', String(next))
    setSearchParams(nextParams, { replace: true })
  }

  return (
    <>
      <ProjectHeader
        project={detail}
        active="monitor"
        counts={detail.counts}
        runs={detail.runs}
        runId={runId}
        onRunChange={changeRun}
        actions={
          <Link className="btn btn-secondary btn-sm" to={`/projects/${detail.id}`}>
            <Icon name="arrow-left" size={13} />
            返回概览
          </Link>
        }
      />

      <main className="page-pad">
        <div className={`connection-bar ${connectionClass}`}>
          <span className="connection-left">
            <span className="dot" style={{ width: 7, height: 7, borderRadius: 999, background: 'currentColor' }} />
            {connectionText}
            {connection === 'demo' && <DemoPill />}
          </span>
          <span className="connection-right">{connectionRight}</span>
        </div>

        <div className="monitor-columns" style={{ height: 'calc(100vh - 268px)', minHeight: 560 }}>
          <div className="column-stack">
            <section className="card stage-summary">
              <div className="stage-summary-head">
                <span className="stage-summary-label">当前阶段</span>
                <span className={`badge badge-${currentStage?.stage_status ?? 'pending'}`}>
                  {currentStage?.stage_status === 'running'
                    ? '执行中'
                    : currentStage?.stage_status === 'success'
                      ? '已完成'
                      : currentStage?.stage_status === 'failed'
                        ? '失败'
                        : '等待中'}
                </span>
              </div>
              <span className="stage-summary-value">
                {currentStage ? STAGE_LABELS[currentStage.stage_name] ?? currentStage.stage_name : '未开始'}
              </span>
              <div className="stage-summary-meta">
                <span>已运行 {elapsedText(currentStage?.started_at ?? null, currentStage?.finished_at ?? null, now)}</span>
                <span>阶段 {currentStageIndex} / 5</span>
              </div>
              <div className="progress-track">
                <div className="progress-fill" style={{ width: `${currentStageProgress}%` }} />
              </div>
            </section>

            <section className="card" style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
              <div className="card-head" style={{ flex: 'none' }}>
                <span className="card-title">角色状态</span>
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>6 类角色</span>
              </div>
              <div className="role-list" style={{ flex: 1, overflow: 'auto' }}>
                {ROLE_ORDER.map((role) => {
                  const meta = ROLE_META[role]
                  const worker = [...(snapshot?.workers ?? [])].reverse().find((item) => item.worker_role === role)
                  const status = worker?.task_status ?? 'idle'
                  return (
                    <div key={role} className={status === 'running' ? 'role-row running' : 'role-row'}>
                      <span className="role-icon" style={{ color: meta.color, background: meta.background }}>
                        <Icon name={meta.icon} size={15} />
                      </span>
                      <span className="role-text">
                        <span className="role-top">
                          <span className="role-name">{meta.label}</span>
                          <WorkerStatusText status={status} />
                        </span>
                        <WorkerDesc worker={worker} />
                      </span>
                    </div>
                  )
                })}
              </div>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  padding: '9px 14px',
                  fontSize: 10,
                  color: 'var(--text-muted)',
                  borderTop: '1px solid var(--border)',
                }}
              >
                <Icon name="shield-check" size={12} />
                角色输出通过 JSON Schema 校验后落库
              </div>
            </section>
          </div>

          <div className="column-stack">
            <section className="card" style={{ height: 300, display: 'flex', flexDirection: 'column' }}>
              <div className="card-head" style={{ flex: 'none' }}>
                <span className="card-title">协作消息</span>
                <div className="log-toolbar" style={{ flexWrap: 'wrap' }}>
                  <select aria-label="监控角色筛选" value={roleFilter} onChange={(event) => setRoleFilter(event.target.value)}>
                    <option value="">全部角色</option>{ROLE_ORDER.map((role) => <option value={role} key={role}>{ROLE_META[role].label}</option>)}
                  </select>
                  {(
                    [
                      ['all', '全部'],
                      ['tool_call', '工具调用'],
                      ['result', '结果'],
                      ['warning', '告警'],
                    ] as [ChatFilter, string][]
                  ).map(([value, label]) => (
                    <button
                      key={value}
                      type="button"
                      className="chip"
                      style={{
                        border: 0,
                        background: chatFilter === value ? 'var(--primary-soft)' : 'var(--neutral-soft)',
                        color: chatFilter === value ? 'var(--primary)' : 'var(--text-secondary)',
                        fontWeight: chatFilter === value ? 600 : 400,
                      }}
                      onClick={() => setChatFilter(value)}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
              <div className="chat-list">
                {filteredMessages.length === 0 ? (
                  <EmptyState compact icon="message-square" title="暂无协作消息" />
                ) : (
                  filteredMessages.map((item) => {
                    const meta = MESSAGE_META[item.message_type] ?? MESSAGE_META.info
                    const roleMeta = ROLE_META[item.worker_role]
                    return (
                      <div className="chat-item" key={item.id}>
                        <span className="chat-avatar" style={{ color: meta.color, background: meta.background }}>
                          {(roleMeta?.label ?? item.worker_role).slice(0, 1)}
                        </span>
                        <span className="chat-body">
                          <span className="chat-meta">
                            <span className="chat-role">{roleMeta?.label ?? item.worker_role}</span>
                            <span className="chat-time">{formatClock(item.created_at)}</span>
                            <span className="chat-type" style={{ color: meta.color, background: meta.background }}>
                              {meta.label}
                            </span>
                          </span>
                          <span className="chat-text">{item.message_text}</span>
                        </span>
                      </div>
                    )
                  })
                )}
              </div>
            </section>

            <section className="card" style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
              <div className="card-head" style={{ flex: 'none' }}>
                <span className="card-title">运行日志</span>
                <select aria-label="监控阶段筛选" value={stageFilter} onChange={(event) => setStageFilter(event.target.value)}>
                  <option value="">全部阶段</option>{snapshot?.stages.map((stage) => <option key={stage.stage_id} value={stage.stage_id}>{STAGE_LABELS[stage.stage_name]}</option>)}
                </select>
                <div className="log-toolbar">
                  {(['debug', 'info', 'warning', 'error'] as const).map((level) => {
                    const active = levels.has(level)
                    const color = level === 'error' ? 'var(--danger)' : level === 'warning' ? 'var(--warning)' : 'var(--success)'
                    return (
                      <button
                        key={level}
                        type="button"
                        className="log-level-chip"
                        style={{ border: 0, background: active ? 'var(--neutral-soft)' : 'transparent', color }}
                        onClick={() => {
                          setLevels((previous) => {
                            const next = new Set(previous)
                            if (next.has(level)) next.delete(level)
                            else next.add(level)
                            return next
                          })
                        }}
                      >
                        {level.toUpperCase()}
                      </button>
                    )
                  })}
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    style={{ height: 24, padding: '0 7px', fontSize: 10, gap: 4 }}
                    onClick={() => setPaused((value) => !value)}
                  >
                    <Icon name="pause" size={10} />
                    {paused ? '恢复滚动' : '暂停滚动'}
                  </button>
                </div>
              </div>
              <RuntimeLogList logs={filteredLogs} paused={paused} />
            </section>
          </div>

          <div className="column-stack monitor-side">
            <section className="card monitor-resource">
              <div className="card-head" style={{ flex: 'none' }}>
                <span className="card-title">资源消耗</span>
                <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>按运行配置定时采样</span>
              </div>
              <div className="resource-body" style={{ flex: 1 }}>
                <div className="metric-block">
                  <div className="metric-head">
                    <span className="metric-label">CPU 使用率</span>
                    <span className="metric-value">{cpu.toFixed(0)}%</span>
                  </div>
                  <div className="metric-track">
                    <div className="metric-fill" style={{ width: `${Math.min(100, cpu)}%`, background: 'var(--primary)' }} />
                  </div>
                  <div className="sparkline">
                    {sparkHeights(cpuSeries).map((height, index) => (
                      <span key={`cpu-${index}`} className="spark-bar" style={{ height, background: 'var(--primary)' }} />
                    ))}
                  </div>
                </div>

                <div className="metric-block">
                  <div className="metric-head">
                    <span className="metric-label">内存使用</span>
                    <span className="metric-value">
                      {memory.toLocaleString('zh-CN')} / 2,048 MB
                    </span>
                  </div>
                  <div className="metric-track">
                    <div
                      className="metric-fill"
                      style={{ width: `${Math.min(100, (memory / 2048) * 100)}%`, background: 'var(--warning)' }}
                    />
                  </div>
                  <div className="sparkline">
                    {sparkHeights(memorySeries).map((height, index) => (
                      <span key={`mem-${index}`} className="spark-bar" style={{ height, background: 'var(--warning)' }} />
                    ))}
                  </div>
                </div>

                <div className="token-box">
                  <div>
                    <div className="token-label">Token 累计</div>
                    <div className="token-value">{token.toLocaleString('zh-CN')}</div>
                  </div>
                  <span className="token-delta">{tokenDelta >= 0 ? '+' : ''}{tokenDelta.toLocaleString('zh-CN')} 较上条记录</span>
                </div>
                <div className="sparkline" aria-label="Token 消耗趋势">
                  {sparkHeights(tokenSeries).map((height, index) => <span key={`token-${index}`} className="spark-bar" style={{ height, background: 'var(--success)' }} />)}
                </div>
              </div>
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  padding: '8px 14px',
                  fontSize: 10,
                  color: 'var(--text-muted)',
                  borderTop: '1px solid var(--border)',
                }}
              >
                <span>最近采样 {formatClock(latest?.recorded_at ?? null)}</span>
                <span>按运行配置采样</span>
              </div>
            </section>

            <section className="card monitor-overview">
              <div className="card-head" style={{ flex: 'none' }}>
                <span className="card-title">本轮概览</span>
              </div>
              <div className="kv-list" style={{ padding: '0 16px' }}>
                <div className="kv-row">
                  <span>当前轮次</span>
                  <strong>第 {snapshot?.selected_run_id ?? detail.selected_run_id} 轮</strong>
                </div>
                <div className="kv-row">
                  <span>已发现漏洞</span>
                  <strong>{vulnTotal} 条</strong>
                </div>
                <div className="kv-row">
                  <span>攻击路径</span>
                  <strong>{detail.counts.attack_paths} 条</strong>
                </div>
                <div className="kv-row">
                  <span>当前阶段</span>
                  <strong>{currentStage ? STAGE_LABELS[currentStage.stage_name] ?? currentStage.stage_name : '—'}</strong>
                </div>
                <div className="kv-row">
                  <span>报告状态</span>
                  <strong>
                    {detail.report_status === 'ready' ? '已生成' : detail.report_status === 'pending' ? '生成中' : '未生成'}
                  </strong>
                </div>
              </div>
              <div style={{ padding: 10, marginTop: 'auto' }}>
                <Link className="btn btn-primary btn-block" to={`/projects/${detail.id}/vulnerabilities${runId ? `?run_id=${runId}` : ''}`}>
                  查看漏洞列表
                  <Icon name="arrow-right" size={13} />
                </Link>
              </div>
            </section>
          </div>
        </div>

        <MonitorHistory projectId={String(detail.id)} runId={runId} />
        {detailError && (
          <div className="alert alert-error mt-16" style={{ marginBottom: 0 }}>
            <Icon name="triangle-alert" size={14} />
            <span>{detailError}</span>
          </div>
        )}
      </main>
    </>
  )
}
