import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { DEMO_MONITOR_SNAPSHOT } from '../api/demo'
import { loadWithDemo } from '../api/demoMode'
import { monitorApi } from '../api/monitor'
import type { ChatMessage } from '../api/monitor'
import { projectApi } from '../api/projects'
import type { ProjectDetail } from '../api/projects'
import { Icon } from '../components/Icon'
import ProjectHeader from '../components/ProjectHeader'
import {
  ConfirmDialog,
  DemoPill,
  EmptyState,
  LoadingBlock,
} from '../components/ui'
import { useProjectDetail } from '../hooks/useProjectDetail'
import { formatClock, formatTime, truncate } from '../utils/format'

const STAGE_ORDER = ['environment_scan', 'code_analysis', 'vulnerability_verify', 'report_generate', 'done']

const STAGE_LABELS: Record<string, string> = {
  environment_scan: '环境检查',
  code_analysis: '代码分析',
  vulnerability_verify: '漏洞验证',
  report_generate: '报告生成',
  done: '收尾',
}

const ROLE_LABELS: Record<string, string> = {
  orchestrator: '通用处理',
  env_inspector: '环境检查',
  code_analyst: '代码分析',
  vuln_verifier: '漏洞验证',
  report_writer: '报告整理',
  ops_assistant: '运维辅助',
}

const ROLE_COLORS: Record<string, { color: string; background: string }> = {
  orchestrator: { color: 'var(--primary)', background: 'var(--primary-soft)' },
  env_inspector: { color: 'var(--success)', background: 'var(--success-soft)' },
  code_analyst: { color: 'var(--high)', background: 'var(--high-soft)' },
  vuln_verifier: { color: 'var(--danger)', background: 'var(--danger-soft)' },
  report_writer: { color: 'var(--neutral)', background: 'var(--neutral-soft)' },
  ops_assistant: { color: 'var(--success)', background: 'var(--success-soft)' },
}

const REPORT_LABELS: Record<string, string> = {
  ready: '已生成',
  pending: '生成中',
  none: '未生成',
}

function messageOf(error: unknown): string {
  return error instanceof ApiError ? error.message : '网络异常，请稍后重试'
}

function formatDuration(ms: number): string {
  const total = Math.max(0, Math.round(ms / 1000))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

function elapsedOf(detail: ProjectDetail): string {
  let total = 0
  let hasData = false
  const now = Date.now()
  for (const stage of detail.stages) {
    if (!stage.started_at) continue
    hasData = true
    const start = new Date(stage.started_at).getTime()
    const end = stage.finished_at ? new Date(stage.finished_at).getTime() : now
    total += Math.max(0, end - start)
  }
  return hasData ? formatDuration(total) : '—'
}

function stageVisual(status: string): {
  className: string
  icon?: 'check' | 'x' | 'loader-circle' | 'pause'
  label: string
} {
  if (status === 'success') return { className: 'success', icon: 'check', label: '成功' }
  if (status === 'failed') return { className: 'failed', icon: 'x', label: '失败' }
  if (status === 'running') return { className: 'running', icon: 'loader-circle', label: '执行中' }
  if (status === 'stopped') return { className: 'stopped', icon: 'pause', label: '已停止' }
  if (status === 'skipped') return { className: 'pending', label: '已跳过' }
  return { className: 'pending', label: '等待中' }
}

export default function ProjectDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [selectedRun, setSelectedRun] = useState<number | null>(null)
  const { detail, loading, error: loadError, reload } = useProjectDetail(id, selectedRun)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [pendingAction, setPendingAction] = useState<'stop' | 'delete' | null>(null)
  const [confirmBusy, setConfirmBusy] = useState(false)
  const [activity, setActivity] = useState<ChatMessage[]>([])
  const [activityDemo, setActivityDemo] = useState(false)

  const runId = selectedRun ?? detail?.current_run_id ?? undefined

  useEffect(() => {
    if (!id) return
    let cancelled = false
    loadWithDemo(
      () => monitorApi.messages(id, { runId, pageSize: 5 }),
      () => ({
        items: DEMO_MONITOR_SNAPSHOT.recent_messages.slice(0, 5),
        total: 5,
        page: 1,
        page_size: 5,
      }),
    )
      .then(({ data, demo }) => {
        if (cancelled) return
        setActivity(data.items)
        setActivityDemo(demo)
      })
      .catch(() => {
        if (!cancelled) setActivity([])
      })
    return () => {
      cancelled = true
    }
  }, [id, runId])

  useEffect(() => {
    if (detail?.project_status !== 'running') return
    const timer = window.setInterval(() => void reload(), 2000)
    return () => window.clearInterval(timer)
  }, [detail?.project_status, reload])

  const currentRun = useMemo(
    () => detail?.runs.find((run) => run.run_id === detail.selected_run_id) ?? null,
    [detail],
  )

  const stageMap = useMemo(() => {
    const map = new Map<string, ProjectDetail['stages'][number]>()
    for (const stage of detail?.stages ?? []) map.set(stage.stage_name, stage)
    return map
  }, [detail])

  const failedStage = detail?.stages.find((stage) => stage.stage_status === 'failed')

  const handleStart = useCallback(async () => {
    if (!detail) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const result = await projectApi.start(detail.id)
      setNotice(`第 ${result.run_id} 轮任务已启动`)
      setSelectedRun(null)
      await reload()
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setBusy(false)
    }
  }, [detail, reload])

  const handleConfirm = useCallback(async () => {
    if (!detail || !pendingAction) return
    setConfirmBusy(true)
    setError('')
    setNotice('')
    try {
      if (pendingAction === 'stop') {
        await projectApi.stop(detail.id)
        setNotice('任务已停止')
        setPendingAction(null)
        await reload()
      } else {
        await projectApi.remove(detail.id)
        navigate('/projects', { replace: true })
        return
      }
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setConfirmBusy(false)
    }
  }, [detail, pendingAction, reload, navigate])

  if (loading && !detail) {
    return (
      <main className="page-pad">
        <LoadingBlock text="正在加载项目详情…" />
      </main>
    )
  }

  if (!detail) {
    return (
      <main className="page-pad">
        <div className="alert alert-error">
          <Icon name="triangle-alert" size={14} />
          <span>{loadError || error || '项目不存在'}</span>
        </div>
        <Link className="btn btn-secondary" to="/projects">
          <Icon name="arrow-left" size={14} />
          返回项目列表
        </Link>
      </main>
    )
  }

  const running = detail.project_status === 'running'
  const canStart = !running
  const reportLabel = REPORT_LABELS[detail.report_status] ?? '未生成'

  return (
    <>
      <ProjectHeader
        project={detail}
        active="overview"
        counts={detail.counts}
        runs={detail.runs}
        runId={selectedRun}
        onRunChange={setSelectedRun}
        actions={
          <>
            {running ? (
              <button
                type="button"
                className="btn btn-secondary"
                disabled={busy}
                onClick={() => setPendingAction('stop')}
              >
                <Icon name="square" size={13} />
                停止任务
              </button>
            ) : (
              <button type="button" className="btn btn-primary" disabled={busy || !canStart} onClick={() => void handleStart()}>
                <Icon name="play" size={13} />
                {detail.project_status === 'created' ? '启动任务' : '重新启动'}
              </button>
            )}
            <button
              type="button"
              className="btn btn-danger-ghost"
              disabled={busy || running}
              title={running ? '请先停止任务' : undefined}
              onClick={() => setPendingAction('delete')}
            >
              <Icon name="trash-2" size={13} />
              删除
            </button>
          </>
        }
      />

      <main className="page-pad">
        {notice && (
          <div className="alert alert-success">
            <Icon name="circle-check" size={14} />
            <span>{notice}</span>
          </div>
        )}
        {error && (
          <div className="alert alert-error">
            <Icon name="triangle-alert" size={14} />
            <span>{error}</span>
          </div>
        )}
        {detail.cleanup_pending && (
          <div className="alert alert-warning">
            <Icon name="triangle-alert" size={14} />
            <span>项目目录清理未完成，管理员可在「系统配置 - 隔离环境维护」中重试删除。</span>
          </div>
        )}
        {running && detail.stages.length === 0 && (
          <div className="alert alert-info">
            <Icon name="info" size={14} />
            <span>正在准备源码与隔离环境，就绪后将自动开始环境检查。</span>
          </div>
        )}

        <section className="card card-body">
          <div className="info-grid">
            <div className="info-cell">
              <span className="info-key">源码来源</span>
              <span className="info-value" title={detail.source_path}>
                {detail.source_type === 'local_path' ? '本地目录' : 'Git 仓库'} · {detail.source_path}
              </span>
            </div>
            <div className="info-cell">
              <span className="info-key">隔离环境</span>
              <span className="info-value">
                {detail.sandbox_type === 'docker' ? 'Docker' : detail.sandbox_type}
                {detail.sandbox_id ? ` · ${detail.sandbox_id}` : ' · 未绑定'}
              </span>
            </div>
            <div className="info-cell">
              <span className="info-key">创建者</span>
              <span className="info-value">用户 #{detail.created_by}</span>
            </div>
            <div className="info-cell">
              <span className="info-key">创建时间</span>
              <span className="info-value">{formatTime(detail.created_at)}</span>
            </div>
            <div className="info-cell">
              <span className="info-key">本轮源码 commit</span>
              <span className="info-value mono" title={currentRun?.source_revision ?? undefined}>
                {currentRun?.source_revision || '—（本地源码）'}
              </span>
            </div>
            <div className="info-cell">
              <span className="info-key">源码 SHA-256 指纹</span>
              <span className="info-value mono" title={currentRun?.source_fingerprint ?? undefined}>
                {currentRun?.source_fingerprint ? truncate(currentRun.source_fingerprint, 30) : '—'}
              </span>
            </div>
          </div>
        </section>

        <section className="card card-body mt-16">
          <div className="flex items-center justify-between mb-12">
            <div>
              <div className="section-title">执行进度</div>
              <div className="field-help">
                第 {detail.selected_run_id || detail.current_run_id || 0} 轮 · 开始于{' '}
                {formatTime(detail.stages.find((stage) => stage.started_at)?.started_at ?? null)}
              </div>
            </div>
            <span className="flex items-center gap-6 muted" style={{ fontSize: 11 }}>
              <Icon name="timer" size={13} />
              阶段超时阈值 3600s
            </span>
          </div>

          <div className="stage-progress">
            {STAGE_ORDER.map((stageName, index) => {
              const stage = stageMap.get(stageName)
              const status = stage?.stage_status ?? 'pending'
              const visual = stageVisual(status)
              const previous = index > 0 ? stageMap.get(STAGE_ORDER[index - 1]) : null
              const connectorDone = previous?.stage_status === 'success'
              return (
                <div key={stageName} style={{ display: 'contents' }}>
                  {index > 0 && (
                    <div className={connectorDone ? 'stage-connector done' : 'stage-connector'}>
                      <span className="line" />
                    </div>
                  )}
                  <div className="stage-step">
                    <span className={`stage-circle ${visual.className}`}>
                      {visual.icon ? (
                        <Icon name={visual.icon} size={14} />
                      ) : (
                        index + 1
                      )}
                    </span>
                    <span className={`stage-name ${visual.className}`}>
                      {STAGE_LABELS[stageName] ?? stageName}
                    </span>
                    <span className={`stage-desc ${visual.className}`}>
                      {stage ? `${visual.label}${stage.finished_at ? ` · ${durationText(stage.started_at, stage.finished_at)}` : ''}` : '等待执行'}
                    </span>
                  </div>
                </div>
              )
            })}
          </div>

          {failedStage?.error_message && (
            <div className="alert alert-error mt-16" style={{ marginBottom: 0 }}>
              <Icon name="triangle-alert" size={14} />
              <span>
                阶段「{STAGE_LABELS[failedStage.stage_name] ?? failedStage.stage_name}」失败：
                {failedStage.error_message}
              </span>
            </div>
          )}
        </section>

        <div className="stat-grid mt-16">
          <div className="stat-card">
            <div className="stat-head">
              <span>漏洞总数</span>
              <Icon name="shield-alert" size={15} />
            </div>
            <span className="stat-value">{detail.counts.vulnerabilities}</span>
            <span className="stat-sub">当前轮次 #{detail.selected_run_id || 0}</span>
            {detail.vulnerability_stats && <>
              <span className="stat-sub">{Object.entries({ critical: '严重', high: '高危', medium: '中危', low: '低危', info: '提示' }).map(([key, label]) => `${label} ${detail.vulnerability_stats?.risk_levels[key] ?? 0}`).join(' · ')}</span>
              <span className="stat-sub">{Object.entries({ pending: '待验证', verified: '已验证', unverified: '未验证', false_positive: '误报' }).map(([key, label]) => `${label} ${detail.vulnerability_stats?.verify_statuses[key] ?? 0}`).join(' · ')}</span>
            </>}
          </div>
          <div className="stat-card">
            <div className="stat-head">
              <span>攻击路径</span>
              <Icon name="route" size={15} />
            </div>
            <span className="stat-value">{detail.counts.attack_paths}</span>
            <span className="stat-sub">已生成的多步利用链</span>
          </div>
          <div className="stat-card">
            <div className="stat-head">
              <span>报告状态</span>
              <Icon name="file-text" size={15} />
            </div>
            <span className="stat-value" style={{ fontSize: 20 }}>
              {reportLabel}
            </span>
            <span className="stat-sub">
              {detail.report_status === 'ready'
                ? '可在报告页预览与下载'
                : detail.report_status === 'pending'
                  ? '报告生成阶段执行中'
                  : '将在第 4 阶段完成后生成'}
            </span>
          </div>
          <div className="stat-card">
            <div className="stat-head">
              <span>本轮耗时</span>
              <Icon name="timer" size={15} />
            </div>
            <span className="stat-value">{elapsedOf(detail)}</span>
            <span className="stat-sub">
              {detail.stages.length > 0 ? '按阶段起止时间累计' : '尚未产生阶段记录'}
            </span>
          </div>
        </div>

        <section className="card mt-16">
          <div className="card-head">
            <div className="flex items-center gap-8">
              <span className="card-title">本轮实时动态</span>
              {activityDemo && <DemoPill />}
            </div>
            <Link className="btn-link" to={`/projects/${detail.id}/monitor${runId ? `?run_id=${runId}` : ''}`}>
              进入实时监控
              <Icon name="arrow-right" size={13} />
            </Link>
          </div>
          {activity.length === 0 ? (
            <EmptyState compact icon="activity" title="本轮暂无协作消息" description="任务启动后，角色协作消息会实时出现在这里。" />
          ) : (
            <div className="activity-list">
              {activity.map((item) => {
                const color = ROLE_COLORS[item.worker_role] ?? { color: 'var(--neutral)', background: 'var(--neutral-soft)' }
                return (
                  <div className="activity-row" key={item.id}>
                    <span className="activity-time">{formatClock(item.created_at)}</span>
                    <span className="role-chip" style={color}>
                      {ROLE_LABELS[item.worker_role] ?? item.worker_role}
                    </span>
                    <span className="activity-msg" title={item.message_text}>
                      {item.message_text}
                    </span>
                  </div>
                )
              })}
            </div>
          )}
        </section>
      </main>

      <ConfirmDialog
        open={pendingAction !== null}
        title={pendingAction === 'stop' ? '停止任务' : '删除项目'}
        description={
          pendingAction === 'stop'
            ? `确定停止项目「${detail.project_name}」的当前任务？当前阶段将立即终止，本轮已产生的数据会保留。`
            : `确认删除项目「${detail.project_name}」？将删除该项目全部轮次的漏洞、攻击路径、报告与运行数据，操作不可恢复。`
        }
        confirmLabel={pendingAction === 'stop' ? '确认停止' : '确认删除'}
        tone={pendingAction === 'stop' ? 'warning' : 'danger'}
        busy={confirmBusy}
        onClose={() => setPendingAction(null)}
        onConfirm={() => void handleConfirm()}
      >
        <div className={`modal-note ${pendingAction === 'stop' ? 'warning' : 'danger'}`}>
          <Icon name="info" size={13} />
          <span>
            {pendingAction === 'stop'
              ? '停止后隔离环境容器与工作目录会保留，便于排查。'
              : '删除前将先销毁保留的隔离环境，并同步清理全部轮次工作区目录。'}
          </span>
        </div>
      </ConfirmDialog>
    </>
  )
}

function durationText(start: string | null, end: string | null): string {
  if (!start || !end) return ''
  return formatDuration(new Date(end).getTime() - new Date(start).getTime())
}
