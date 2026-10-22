import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { DEMO_REPORT } from '../api/demo'
import { loadWithDemo } from '../api/demoMode'
import { reportApi } from '../api/reports'
import type { ReportData } from '../api/reports'
import { Icon } from '../components/Icon'
import ProjectHeader from '../components/ProjectHeader'
import { DemoPill, EmptyState, LoadingBlock } from '../components/ui'
import { useProjectDetail } from '../hooks/useProjectDetail'
import { useProjectStream } from '../hooks/useProjectStream'
import { formatTime } from '../utils/format'

const STAGE_ORDER = ['environment_scan', 'code_analysis', 'vulnerability_verify', 'report_generate', 'done']

const STAGE_LABELS: Record<string, string> = {
  environment_scan: '环境检查',
  code_analysis: '代码分析',
  vulnerability_verify: '漏洞验证',
  report_generate: '报告生成',
  done: '收尾',
}

type TocItem = { id: string; label: string }

function messageOf(error: unknown): string {
  return error instanceof ApiError ? error.message : '网络异常，请稍后重试'
}

export default function ReportPage() {
  const { id } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const runParam = searchParams.get('run_id')
  const parsedRun = runParam ? Number(runParam) : null
  const runId = parsedRun !== null && Number.isFinite(parsedRun) ? parsedRun : null
  const { detail, loading: detailLoading, error: detailError } = useProjectDetail(id, runId)
  const { revision } = useProjectStream(id, runId)

  const [report, setReport] = useState<ReportData | null>(null)
  const [demo, setDemo] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [notReady, setNotReady] = useState(false)
  const [activeToc, setActiveToc] = useState('')
  const requestId = useRef(0)

  const load = useCallback(async () => {
    if (!id) return
    const current = ++requestId.current
    setLoading(true)
    setReport(null)
    setError('')
    setNotReady(false)
    try {
      const result = await loadWithDemo(
        () => reportApi.get(id, runId),
        () => DEMO_REPORT,
      )
      if (current !== requestId.current) return
      setReport(result.data)
      setDemo(result.demo)
    } catch (err) {
      if (current !== requestId.current) return
      if (err instanceof ApiError && err.code === 40401) {
        setReport(null)
        setNotReady(true)
      } else {
        setError(messageOf(err))
      }
    } finally {
      if (current === requestId.current) setLoading(false)
    }
  }, [id, runId])

  useEffect(() => {
    void load()
    return () => { requestId.current += 1 }
  }, [load, revision])

  const parsed = useMemo(() => {
    if (!report) return { html: '', toc: [] as TocItem[] }
    try {
      const documentNode = new DOMParser().parseFromString(report.report_html, 'text/html')
      const headings = Array.from(documentNode.querySelectorAll('h2'))
      const toc = headings.map((heading, index) => {
        const id = heading.id || `report-section-${index}`
        heading.id = id
        return { id, label: (heading.textContent?.trim() || `章节 ${index + 1}`).replace(/^\d+[.、]\s*/, '') }
      })
      return { html: documentNode.body.innerHTML, toc }
    } catch {
      return { html: report.report_html, toc: [] as TocItem[] }
    }
  }, [report])

  useEffect(() => {
    if (!activeToc && parsed.toc[0]) setActiveToc(parsed.toc[0].id)
  }, [parsed.toc, activeToc])

  const scrollTo = (tocId: string) => {
    setActiveToc(tocId)
    document.getElementById(tocId)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const changeRun = (next: number) => {
    const nextParams = new URLSearchParams(searchParams)
    nextParams.set('run_id', String(next))
    setSearchParams(nextParams, { replace: true })
  }

  if (detailLoading && !detail) {
    return (
      <main className="page-pad">
        <LoadingBlock text="正在加载项目与报告数据…" />
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

  const effectiveRunId = report?.run_id ?? runId ?? detail.selected_run_id ?? detail.current_run_id
  const markdownUrl = reportApi.downloadUrl(detail.id, effectiveRunId, 'md')
  const htmlUrl = reportApi.downloadUrl(detail.id, effectiveRunId, 'html')
  const stageMap = new Map(detail.stages.map((stage) => [stage.stage_name, stage]))

  return (
    <>
      <ProjectHeader
        project={detail}
        active="report"
        counts={detail.counts}
        runs={detail.runs}
        runId={runId}
        onRunChange={changeRun}
      />

      <main className="page-pad">
        <div className="report-toolbar">
          <div className="report-title-group">
            <h1 className="page-title" style={{ fontSize: 20 }}>安全评估报告</h1>
            {report ? (
              <span className="badge badge-ready">
                <span className="dot" />
                已生成
              </span>
            ) : (
              <span className="badge badge-pending">
                <span className="dot" />
                未生成
              </span>
            )}
            {report && (
              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                生成于 {formatTime(report.created_at)}
              </span>
            )}
            {demo && <DemoPill />}
          </div>
          <div className="page-actions">
            {report ? (
              <>
                <a className="btn btn-secondary" href={markdownUrl} download>
                  <Icon name="download" size={13} />
                  下载 Markdown
                </a>
                <a className="btn btn-secondary" href={htmlUrl} download>
                  <Icon name="download" size={13} />
                  下载 HTML
                </a>
                <button type="button" className="btn btn-ghost" onClick={() => window.print()}>
                  <Icon name="printer" size={13} />
                  打印
                </button>
              </>
            ) : (
              <>
                <span className="btn btn-secondary" aria-disabled="true" style={{ opacity: 0.5 }}>
                  <Icon name="download" size={13} />
                  下载 Markdown
                </span>
                <span className="btn btn-secondary" aria-disabled="true" style={{ opacity: 0.5 }}>
                  <Icon name="download" size={13} />
                  下载 HTML
                </span>
              </>
            )}
          </div>
        </div>

        {error && (
          <div className="alert alert-error">
            <Icon name="triangle-alert" size={14} />
            <span>{error}</span>
            <button type="button" className="btn-link" style={{ marginLeft: 'auto' }} onClick={() => void load()}>
              重试
            </button>
          </div>
        )}

        {loading ? (
          <LoadingBlock text="正在加载报告…" />
        ) : report ? (
          <div className="report-layout">
            <aside className="card toc-card">
              <div className="toc-title">目录</div>
              {parsed.toc.length === 0 ? (
                <div className="field-help">报告未提供章节标题。</div>
              ) : (
                parsed.toc.map((item, index) => (
                  <button
                    key={item.id}
                    type="button"
                    className={activeToc === item.id ? 'toc-item active' : 'toc-item'}
                    onClick={() => scrollTo(item.id)}
                  >
                    <span className="toc-num">{String(index + 1).padStart(2, '0')}</span>
                    <span>{item.label}</span>
                  </button>
                ))
              )}
              <div className="toc-spacer" />
              <div className="report-files">
                <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-secondary)' }}>报告文件</div>
                <a className="report-file-row" href={markdownUrl} download>
                  <Icon name="file-text" size={12} />
                  report-run-{effectiveRunId}.md
                </a>
                <a className="report-file-row" href={htmlUrl} download>
                  <Icon name="file-text" size={12} />
                  report-run-{effectiveRunId}.html
                </a>
              </div>
            </aside>

            <article className="card report-doc">
              <div
                className="report-html"
                // 报告 HTML 由后端按 PRD 15.8 白名单消毒后返回
                dangerouslySetInnerHTML={{ __html: parsed.html }}
              />
            </article>
          </div>
        ) : notReady && !error ? (
          <section className="card">
            <EmptyState
              icon="file-clock"
              title="报告尚未生成"
              description="报告将在第 4 阶段（报告生成）完成后自动生成，并在生成后推送 report_ready 通知。"
              action={
                <div className="report-empty-progress">
                  {STAGE_ORDER.map((stageName) => {
                    const stage = stageMap.get(stageName)
                    const status = stage?.stage_status ?? 'pending'
                    const color =
                      status === 'success'
                        ? 'var(--success)'
                        : status === 'running'
                          ? 'var(--primary)'
                          : status === 'failed'
                            ? 'var(--danger)'
                            : 'var(--neutral)'
                    const background =
                      status === 'success'
                        ? 'var(--success-soft)'
                        : status === 'running'
                          ? 'var(--primary-soft)'
                          : status === 'failed'
                            ? 'var(--danger-soft)'
                            : 'var(--neutral-soft)'
                    return (
                      <span key={stageName} className="chip" style={{ color, background }}>
                        <span style={{ width: 5, height: 5, borderRadius: 999, background: 'currentColor' }} />
                        {STAGE_LABELS[stageName]}
                      </span>
                    )
                  })}
                </div>
              }
            />
            {detail.stages.length > 0 && (
              <div className="field-help" style={{ textAlign: 'center', paddingBottom: 28 }}>
                当前阶段：
                {STAGE_LABELS[
                  detail.stages.find((stage) => stage.stage_status === 'running')?.stage_name ??
                    detail.stages[detail.stages.length - 1]?.stage_name ??
                    ''
                ] ?? '未开始'}
              </div>
            )}
            <div style={{ display: 'flex', justifyContent: 'center', paddingBottom: 40 }}>
              <Link className="btn btn-primary" to={`/projects/${detail.id}/monitor${runId ? `?run_id=${runId}` : ''}`}>
                进入实时监控
                <Icon name="arrow-right" size={13} />
              </Link>
            </div>
          </section>
        ) : null}

        {notReady && !loading && !report && !error && (
          <p className="field-help" style={{ textAlign: 'center' }}>
            报告生成后可直接在本页预览、下载 Markdown / HTML 或使用浏览器打印。
          </p>
        )}
      </main>
    </>
  )
}
