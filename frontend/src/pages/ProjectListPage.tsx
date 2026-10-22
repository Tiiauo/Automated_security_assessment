import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ApiError } from '../api/client'
import { projectApi } from '../api/projects'
import type { Project, ProjectList, ProjectStatus } from '../api/projects'
import { Icon } from '../components/Icon'
import { ConfirmDialog, EmptyState, PageHead, StatusBadge } from '../components/ui'
import { formatTime, truncate } from '../utils/format'

const STATUS_OPTIONS: { value: ProjectStatus | ''; label: string }[] = [
  { value: '', label: '全部状态' },
  { value: 'created', label: '已创建' },
  { value: 'running', label: '运行中' },
  { value: 'completed', label: '已完成' },
  { value: 'failed', label: '失败' },
  { value: 'stopped', label: '已停止' },
]

type PendingAction = { type: 'stop' | 'delete'; project: Project } | null

function messageOf(error: unknown): string {
  return error instanceof ApiError ? error.message : '网络异常，请稍后重试'
}

export default function ProjectListPage() {
  const [list, setList] = useState<ProjectList | null>(null)
  const [status, setStatus] = useState<ProjectStatus | ''>('')
  const [keywordInput, setKeywordInput] = useState('')
  const [keyword, setKeyword] = useState('')
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [pendingAction, setPendingAction] = useState<PendingAction>(null)
  const [confirmBusy, setConfirmBusy] = useState(false)
  const navigate = useNavigate()

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setList(await projectApi.list({ status, keyword, page }))
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setLoading(false)
    }
  }, [status, keyword, page])

  useEffect(() => {
    void load()
  }, [load])

  const handleStart = async (project: Project) => {
    setBusyId(project.id)
    setError('')
    setNotice('')
    try {
      const result = await projectApi.start(project.id)
      setNotice(`第 ${result.run_id} 轮任务已启动`)
      await load()
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setBusyId(null)
    }
  }

  const handleConfirm = async () => {
    if (!pendingAction) return
    const { type, project } = pendingAction
    setConfirmBusy(true)
    setError('')
    setNotice('')
    try {
      if (type === 'stop') {
        await projectApi.stop(project.id)
        setNotice('任务已停止')
      } else {
        await projectApi.remove(project.id)
        setNotice('项目已删除')
        if (list && list.items.length === 1 && page > 1) {
          setPage(page - 1)
        }
      }
      setPendingAction(null)
      await load()
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setConfirmBusy(false)
    }
  }

  const totalPages = list ? Math.max(1, Math.ceil(list.total / list.page_size)) : 1

  return (
    <main className="page-pad">
      <PageHead
        title="项目"
        subtitle="管理源码项目，启动自动化安全评估任务"
        actions={
          <Link className="btn btn-primary" to="/projects/new">
            <Icon name="plus" size={15} />
            新建项目
          </Link>
        }
      />

      <div className="filter-bar mb-16">
        <div className="input-wrap filter-search">
          <span className="input-icon">
            <Icon name="search" size={15} />
          </span>
          <input
            className="input"
            value={keywordInput}
            onChange={(event) => setKeywordInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                setKeyword(keywordInput.trim())
                setPage(1)
              }
            }}
            placeholder="搜索项目名称"
          />
        </div>
        <select
          className="select filter-select"
          value={status}
          onChange={(event) => {
            setStatus(event.target.value as ProjectStatus | '')
            setPage(1)
          }}
        >
          {STATUS_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => {
            setKeyword(keywordInput.trim())
            setPage(1)
          }}
        >
          查询
        </button>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() => {
            setKeywordInput('')
            setKeyword('')
            setStatus('')
            setPage(1)
          }}
        >
          重置
        </button>
        <span className="filter-spacer" />
        <span className="muted" style={{ fontSize: 12 }}>
          共 {list?.total ?? 0} 个项目
        </span>
      </div>

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
          <button type="button" className="btn-link" style={{ marginLeft: 'auto' }} onClick={() => void load()}>
            重试
          </button>
        </div>
      )}

      <div className="table-card">
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>项目名称</th>
                <th style={{ width: 340 }}>源码来源</th>
                <th style={{ width: 110 }}>状态</th>
                <th style={{ width: 170 }}>最近启动时间</th>
                <th style={{ width: 170 }}>最近完成时间</th>
                <th style={{ width: 180 }}>操作</th>
              </tr>
            </thead>
            <tbody>
              {loading &&
                Array.from({ length: 5 }, (_, index) => (
                  <tr key={`skeleton-${index}`}>
                    <td>
                      <div className="skeleton" style={{ width: 180 }} />
                      <div className="skeleton mt-8" style={{ width: 110, height: 9 }} />
                    </td>
                    <td>
                      <div className="skeleton" style={{ width: 240 }} />
                    </td>
                    <td>
                      <div className="skeleton" style={{ width: 64, height: 20, borderRadius: 999 }} />
                    </td>
                    <td>
                      <div className="skeleton" style={{ width: 130 }} />
                    </td>
                    <td>
                      <div className="skeleton" style={{ width: 130 }} />
                    </td>
                    <td>
                      <div className="skeleton" style={{ width: 90, marginLeft: 'auto' }} />
                    </td>
                  </tr>
                ))}

              {!loading && list?.items.map((project) => {
                const busy = busyId === project.id
                const running = project.project_status === 'running'
                return (
                  <tr key={project.id}>
                    <td>
                      <button
                        type="button"
                        className="link-action"
                        style={{ color: 'var(--text)', fontWeight: 500, fontSize: 14 }}
                        onClick={() => navigate(`/projects/${project.id}`)}
                      >
                        {project.project_name}
                      </button>
                      <div className="cell-sub">
                        {project.current_run_id > 0 ? `第 ${project.current_run_id} 轮` : '尚未启动'}
                        {project.cleanup_pending && <span className="badge badge-warning badge-sm" style={{ marginLeft: 8 }}>待清理</span>}
                      </div>
                    </td>
                    <td>
                      <div className="cell-source">
                        <Icon
                          name={project.source_type === 'git_repo' ? 'git-branch' : 'folder'}
                          size={15}
                          style={{ color: 'var(--text-muted)' }}
                        />
                        <div className="cell-source-text" style={{ minWidth: 0 }}>
                          <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                            {project.source_type === 'git_repo' ? 'Git 仓库' : '本地目录'}
                          </span>
                          <span className="cell-path" title={project.source_path}>
                            {truncate(project.source_path, 42)}
                          </span>
                        </div>
                      </div>
                    </td>
                    <td>
                      <StatusBadge status={project.project_status} />
                    </td>
                    <td className="muted">{formatTime(project.last_started_at)}</td>
                    <td className="muted">{formatTime(project.last_finished_at)}</td>
                    <td>
                      <div className="cell-actions">
                        <button type="button" className="link-action" onClick={() => navigate(`/projects/${project.id}`)}>
                          查看
                        </button>
                        {running ? (
                          <>
                            <button
                              type="button"
                              className="link-action muted"
                              disabled={busy}
                              onClick={() => setPendingAction({ type: 'stop', project })}
                            >
                              停止
                            </button>
                            <button type="button" className="link-action muted" disabled title="请先停止任务">
                              删除
                            </button>
                          </>
                        ) : (
                          <>
                            <button
                              type="button"
                              className="link-action"
                              disabled={busy}
                              onClick={() => void handleStart(project)}
                            >
                              {project.project_status === 'created' ? '启动' : '重新启动'}
                            </button>
                            <button
                              type="button"
                              className="link-action muted"
                              disabled={busy}
                              onClick={() => setPendingAction({ type: 'delete', project })}
                            >
                              删除
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {!loading && list && list.items.length === 0 && (
          <EmptyState
            icon="folder-plus"
            title={keyword || status ? '没有符合条件的项目' : '还没有项目'}
            description={
              keyword || status
                ? '调整筛选条件后重试，或清空筛选查看全部项目。'
                : '创建第一个项目，接入源码并启动自动化安全评估。'
            }
            action={
              <Link className="btn btn-primary" to="/projects/new">
                <Icon name="plus" size={14} />
                新建项目
              </Link>
            }
          />
        )}

        {!loading && list && list.items.length > 0 && (
          <div className="pagination-bar">
            <span>
              共 {list.total} 条 · 每页 {list.page_size} 条
            </span>
            <div className="pager">
              <button
                type="button"
                disabled={page <= 1}
                onClick={() => setPage(page - 1)}
                aria-label="上一页"
              >
                <Icon name="chevron-left" size={14} />
              </button>
              <button type="button" className="active" aria-current="page">
                {page}
              </button>
              <button
                type="button"
                disabled={page >= totalPages}
                onClick={() => setPage(page + 1)}
                aria-label="下一页"
              >
                <Icon name="chevron-right" size={14} />
              </button>
            </div>
          </div>
        )}
      </div>

      <ConfirmDialog
        open={pendingAction !== null}
        title={pendingAction?.type === 'stop' ? '停止任务' : '删除项目'}
        description={
          pendingAction?.type === 'stop'
            ? `确定停止项目「${pendingAction.project.project_name}」的当前任务？当前阶段将立即终止，本轮已产生的数据会保留。`
            : pendingAction
              ? `确认删除项目「${pendingAction.project.project_name}」？将删除该项目全部轮次的漏洞、攻击路径、报告与运行数据，操作不可恢复。`
              : ''
        }
        confirmLabel={pendingAction?.type === 'stop' ? '确认停止' : '确认删除'}
        tone={pendingAction?.type === 'stop' ? 'warning' : 'danger'}
        busy={confirmBusy}
        onClose={() => setPendingAction(null)}
        onConfirm={() => void handleConfirm()}
      >
        <div className={`modal-note ${pendingAction?.type === 'stop' ? 'warning' : 'danger'}`}>
          <Icon name="info" size={13} />
          <span>
            {pendingAction?.type === 'stop'
              ? '停止后隔离环境容器与工作目录会保留，便于排查。'
              : '删除前将先销毁保留的隔离环境，并同步清理全部轮次工作区目录。'}
          </span>
        </div>
      </ConfirmDialog>
    </main>
  )
}
