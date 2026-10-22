import { useCallback, useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { attackPathApi } from '../api/attackPaths'
import type { AttackPathDetail, AttackPathSummary } from '../api/attackPaths'
import { DEMO_ATTACK_PATHS } from '../api/demo'
import { loadWithDemo } from '../api/demoMode'
import type { RiskLevel, VulnerabilitySummary } from '../api/vulnerabilities'
import { Icon } from '../components/Icon'
import ProjectHeader from '../components/ProjectHeader'
import {
  DemoPill,
  EmptyState,
  LoadingBlock,
  RiskBadge,
  VerifyBadge,
} from '../components/ui'
import { useProjectDetail } from '../hooks/useProjectDetail'
import { useProjectStream } from '../hooks/useProjectStream'

const RISK_LABELS: Record<RiskLevel, string> = {
  critical: '严重',
  high: '高危',
  medium: '中危',
  low: '低危',
  info: '提示',
}

const RISK_COLORS: Record<RiskLevel, { color: string; background: string }> = {
  critical: { color: 'var(--danger)', background: 'var(--danger-soft)' },
  high: { color: 'var(--high)', background: 'var(--high-soft)' },
  medium: { color: 'var(--warning)', background: 'var(--warning-soft)' },
  low: { color: 'var(--low)', background: 'var(--low-soft)' },
  info: { color: 'var(--neutral)', background: 'var(--neutral-soft)' },
}

function messageOf(error: unknown): string {
  return error instanceof ApiError ? error.message : '网络异常，请稍后重试'
}

function summaryOf(path: AttackPathDetail): AttackPathSummary {
  return {
    id: path.id,
    project_id: path.project_id,
    run_id: path.run_id,
    path_code: path.path_code,
    path_title: path.path_title,
    path_summary: path.path_summary,
    final_impact_text: path.final_impact_text,
    step_count: path.step_count,
    vulns: path.vulns,
  }
}

function needsReview(vulns: VulnerabilitySummary[]): boolean {
  return vulns.some((vuln) => vuln.verify_status === 'unverified' || vuln.verify_status === 'pending')
}

function RiskChip({ level, code }: { level: RiskLevel; code: string }) {
  const colors = RISK_COLORS[level]
  return (
    <span className="chip" style={{ color: colors.color, background: colors.background }}>
      <span className="mono">{code}</span> · {RISK_LABELS[level]}
    </span>
  )
}

export default function AttackPathsPage() {
  const { id } = useParams()
  const [searchParams] = useSearchParams()
  const runParam = searchParams.get('run_id')
  const parsedRun = runParam ? Number(runParam) : null
  const runId = parsedRun !== null && Number.isFinite(parsedRun) ? parsedRun : null
  const { detail, loading: detailLoading, error: detailError } = useProjectDetail(id, runId)
  const { revision } = useProjectStream(id, runId)

  const [paths, setPaths] = useState<AttackPathSummary[]>([])
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [demo, setDemo] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const [details, setDetails] = useState<Record<number, AttackPathDetail>>({})
  const [loadingDetail, setLoadingDetail] = useState<Set<number>>(new Set())

  const fetchDetail = useCallback(
    async (path: AttackPathSummary) => {
      if (!id) return
      setLoadingDetail((previous) => new Set(previous).add(path.id))
      try {
        const result = await loadWithDemo(
          () => attackPathApi.detail(id, path.id),
          () => {
            const found = DEMO_ATTACK_PATHS.find((item) => item.id === path.id)
            if (!found) throw new Error('未找到攻击路径详情')
            return found
          },
        )
        setDetails((previous) => ({ ...previous, [path.id]: result.data }))
      } catch (err) {
        setError(messageOf(err))
      } finally {
        setLoadingDetail((previous) => {
          const next = new Set(previous)
          next.delete(path.id)
          return next
        })
      }
    },
    [id],
  )

  const load = useCallback(async () => {
    if (!id) return
    setLoading(true)
    setError('')
    try {
      const result = await loadWithDemo(
        () => attackPathApi.list(id, { runId, page }),
        () => ({
          items: DEMO_ATTACK_PATHS.map(summaryOf),
          total: DEMO_ATTACK_PATHS.length,
          page: 1,
          page_size: 20,
        }),
      )
      setPaths(result.data.items)
      setTotal(result.data.total)
      setDemo(result.demo)
      const first = result.data.items[0]
      if (first) {
        setExpanded(new Set([first.id]))
        void fetchDetail(first)
      }
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setLoading(false)
    }
  }, [id, runId, page, fetchDetail])

  useEffect(() => {
    void load()
  }, [load, revision])

  const toggle = (path: AttackPathSummary) => {
    setExpanded((previous) => {
      const next = new Set(previous)
      if (next.has(path.id)) {
        next.delete(path.id)
      } else {
        next.add(path.id)
        if (!details[path.id]) void fetchDetail(path)
      }
      return next
    })
  }

  const reviewCount = paths.filter((path) => needsReview(path.vulns)).length

  if (detailLoading && !detail) {
    return (
      <main className="page-pad">
        <LoadingBlock text="正在加载项目与攻击路径数据…" />
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

  return (
    <>
      <ProjectHeader project={detail} active="attack-paths" counts={detail.counts} runs={detail.runs} runId={runId} />

      <main className="page-pad">
        <div className="page-head" style={{ marginBottom: 14 }}>
          <div>
            <div className="flex items-center gap-8">
              <h1 className="page-title" style={{ fontSize: 20 }}>攻击路径</h1>
              {demo && <DemoPill />}
            </div>
            <div className="page-subtitle">基于本轮非误报漏洞整理的多步利用链</div>
          </div>
          <div className="role-tag-list">
            <span className="chip" style={{ color: 'var(--text-primary)', background: 'var(--neutral-soft)', padding: '4px 9px' }}>
              {paths.length} 条路径
            </span>
            {reviewCount > 0 && (
              <span className="chip" style={{ color: 'var(--warning)', background: 'var(--warning-soft)', padding: '4px 9px' }}>
                <span style={{ width: 6, height: 6, borderRadius: 999, background: 'currentColor' }} />
                {reviewCount} 条含待复核节点
              </span>
            )}
          </div>
        </div>

        {error && (
          <div className="alert alert-error">
            <Icon name="triangle-alert" size={14} />
            <span>{error}</span>
          </div>
        )}

        {loading ? (
          <LoadingBlock text="正在加载攻击路径…" />
        ) : paths.length === 0 ? (
          <section className="card">
            <EmptyState
              icon="route"
              title="未发现可串联的多步攻击路径"
              description="若本轮无漏洞，或漏洞之间无法构成多步利用链，攻击路径列表为空，阶段仍正常成功。"
            />
          </section>
        ) : (
          <div className="column-stack">
            {paths.map((path) => {
              const isOpen = expanded.has(path.id)
              const pathDetail = details[path.id]
              const flagged = needsReview(path.vulns)
              return (
                <section className="card" key={path.id}>
                  <button
                    type="button"
                    onClick={() => toggle(path)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      width: '100%',
                      padding: '14px 18px',
                      gap: 12,
                      textAlign: 'left',
                      background: 'none',
                      border: 0,
                      borderBottom: isOpen ? '1px solid var(--border)' : 'none',
                    }}
                  >
                    <span className="flex items-center gap-10" style={{ minWidth: 0 }}>
                      <span className="mono" style={{ color: 'var(--primary)', fontSize: 12, fontWeight: 600 }}>
                        {path.path_code}
                      </span>
                      <span style={{ fontSize: 15, fontWeight: 600 }}>{path.path_title}</span>
                      {flagged && (
                        <span className="badge badge-unverified">
                          <span className="dot" />
                          含待人工复核节点
                        </span>
                      )}
                    </span>
                    <span className="flex items-center gap-14" style={{ flex: 'none' }}>
                      {!isOpen && (
                        <span style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
                          {path.step_count} 步 · 最终影响：{path.final_impact_text ?? '—'}
                        </span>
                      )}
                      {isOpen && <span className="badge badge-info">{path.step_count} 个利用步骤</span>}
                      <Icon name={isOpen ? 'chevron-up' : 'chevron-down'} size={16} style={{ color: 'var(--text-muted)' }} />
                    </span>
                  </button>

                  {isOpen && (
                    <div className="card-body" style={{ padding: '16px 18px' }}>
                      <div className="meta-row mb-16">
                        <span className="flex items-center gap-6">
                          关联漏洞
                          <span className="role-tag-list">
                            {path.vulns.map((vuln) => (
                              <RiskChip key={vuln.id} level={vuln.risk_level} code={vuln.vuln_code} />
                            ))}
                          </span>
                        </span>
                        <span>
                          利用顺序
                          <strong style={{ marginLeft: 6 }}>
                            {path.vulns.map((vuln, index) => `${index + 1} ${vuln.vuln_title}`).join(' → ')}
                          </strong>
                        </span>
                      </div>

                      {pathDetail ? (
                        <div className="timeline">
                          {pathDetail.steps.map((step, index) => (
                            <div className="timeline-step" key={`${path.id}-${step.step_order}`}>
                              <div className="timeline-rail">
                                <span
                                  className="timeline-dot"
                                  style={{ background: index === 0 ? 'var(--primary)' : 'var(--danger)' }}
                                >
                                  {String(step.step_order).padStart(2, '0')}
                                </span>
                                {index < pathDetail.steps.length - 1 && <span className="timeline-line" />}
                              </div>
                              <div className="timeline-body">
                                <div className="timeline-title">{step.vuln.vuln_title}</div>
                                <div className="timeline-desc">{step.step_text}</div>
                                <div className="timeline-meta">
                                  <span className="mono" style={{ color: 'var(--primary)' }}>
                                    {step.vuln.vuln_code}
                                  </span>
                                  <RiskBadge level={step.vuln.risk_level} />
                                  <VerifyBadge status={step.vuln.verify_status} />
                                </div>
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : loadingDetail.has(path.id) ? (
                        <LoadingBlock text="正在加载步骤明细…" />
                      ) : (
                        <div className="field-help">步骤明细将在攻击路径详情接口接入后展示。</div>
                      )}

                      <div className="impact-bar mt-8">
                        <Icon name="target" size={14} />
                        <span>最终影响：{path.final_impact_text ?? '—'}</span>
                      </div>
                    </div>
                  )}
                </section>
              )
            })}

            <section className="card card-body">
              <div className="section-title mb-12" style={{ fontSize: 14 }}>路径判定说明</div>
              <div className="check-list">
                {[
                  '每条路径至少包含 2 个存在因果串联关系的利用步骤。',
                  '仅串联非误报漏洞；误报漏洞不会进入攻击路径。',
                  '路径中包含未验证漏洞时，卡片与报告均标注「含待人工复核节点」。',
                  '步骤按 step_order 排列，同一轮次内路径编号唯一。',
                  '路径编号规则 PATH-{序号:03d}，同一项目同一轮次内唯一。',
                  '删除漏洞时级联删除关联步骤，保证路径数据一致。',
                ].map((text) => (
                  <div className="check-row" key={text}>
                    <Icon name="circle-check" size={14} />
                    <span>{text}</span>
                  </div>
                ))}
              </div>
              <div className="modal-note primary mt-16">
                <Icon name="info" size={13} />
                <span>若本轮未发现可串联的漏洞，攻击路径列表为空（0 条），但阶段仍判定成功。</span>
              </div>
            </section>
          </div>
        )}
        <div className="page-actions" style={{ marginTop: 16 }}>
          <button type="button" className="btn btn-secondary" disabled={page <= 1 || loading} onClick={() => setPage(page - 1)}>上一页</button>
          <span>{page} / {Math.max(1, Math.ceil(total / 20))} 页 · {total} 条路径</span>
          <button type="button" className="btn btn-secondary" disabled={page * 20 >= total || loading} onClick={() => setPage(page + 1)}>下一页</button>
        </div>
      </main>
    </>
  )
}
