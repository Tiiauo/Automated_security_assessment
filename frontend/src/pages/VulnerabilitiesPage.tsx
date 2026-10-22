import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { DEMO_VULNERABILITIES, DEMO_VULNERABILITY_SUMMARIES } from '../api/demo'
import { loadWithDemo } from '../api/demoMode'
import { vulnerabilityApi } from '../api/vulnerabilities'
import type {
  RiskLevel,
  VerifyStatus,
  VulnerabilityDetail,
  VulnerabilityList,
  VulnerabilitySummary,
} from '../api/vulnerabilities'
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
import { truncate } from '../utils/format'

const RISK_OPTIONS: { value: RiskLevel | ''; label: string }[] = [
  { value: '', label: '全部等级' },
  { value: 'critical', label: '严重' },
  { value: 'high', label: '高危' },
  { value: 'medium', label: '中危' },
  { value: 'low', label: '低危' },
  { value: 'info', label: '提示' },
]

const VERIFY_OPTIONS: { value: VerifyStatus | ''; label: string }[] = [
  { value: '', label: '全部状态' },
  { value: 'pending', label: '待验证' },
  { value: 'verified', label: '已验证' },
  { value: 'unverified', label: '未验证' },
  { value: 'false_positive', label: '误报' },
]

const RISK_SUMMARY = [
  { key: 'critical' as const, label: '严重', color: 'var(--danger)', background: 'var(--danger-soft)' },
  { key: 'high' as const, label: '高危', color: 'var(--high)', background: 'var(--high-soft)' },
  { key: 'medium' as const, label: '中危', color: 'var(--warning)', background: 'var(--warning-soft)' },
  { key: 'low' as const, label: '低危', color: 'var(--low)', background: 'var(--low-soft)' },
  { key: 'info' as const, label: '提示', color: 'var(--neutral)', background: 'var(--neutral-soft)' },
]

const STAGE_LABELS: Record<string, string> = {
  environment_scan: '环境检查',
  code_analysis: '代码分析',
  vulnerability_verify: '漏洞验证',
  report_generate: '报告生成',
  done: '收尾',
}

const STAGE_ID_LABELS: Record<number, string> = {
  1: '环境检查',
  2: '代码分析',
  3: '漏洞验证',
  4: '报告生成',
  5: '收尾',
}

function messageOf(error: unknown): string {
  return error instanceof ApiError ? error.message : '网络异常，请稍后重试'
}

function demoList(risk: RiskLevel | '', verify: VerifyStatus | '', keyword: string, page: number): VulnerabilityList {
  const filtered = DEMO_VULNERABILITY_SUMMARIES.filter((item) => {
    if (risk && item.risk_level !== risk) return false
    if (verify && item.verify_status !== verify) return false
    if (keyword) {
      const haystack = `${item.vuln_code} ${item.vuln_title} ${item.file_path ?? ''}`.toLowerCase()
      if (!haystack.includes(keyword.toLowerCase())) return false
    }
    return true
  })
  const pageSize = 20
  return {
    items: filtered.slice((page - 1) * pageSize, page * pageSize),
    total: filtered.length,
    page,
    page_size: pageSize,
  }
}

function linesOf(text: string | null): string[] {
  if (!text) return []
  return text
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean)
}

export default function VulnerabilitiesPage() {
  const { id } = useParams()
  const [searchParams] = useSearchParams()
  const runParam = searchParams.get('run_id')
  const parsedRun = runParam ? Number(runParam) : null
  const runId = parsedRun !== null && Number.isFinite(parsedRun) ? parsedRun : null
  const { detail, loading: detailLoading, error: detailError } = useProjectDetail(id, runId)
  const { revision } = useProjectStream(id, runId)

  const [risk, setRisk] = useState<RiskLevel | ''>('')
  const [verify, setVerify] = useState<VerifyStatus | ''>('')
  const [keywordInput, setKeywordInput] = useState('')
  const [keyword, setKeyword] = useState('')
  const [page, setPage] = useState(1)
  const [list, setList] = useState<VulnerabilityList | null>(null)
  const [demo, setDemo] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [selected, setSelected] = useState<VulnerabilityDetail | null>(null)
  const [detailDemo, setDetailDemo] = useState(false)
  const [drawerLoading, setDrawerLoading] = useState(false)

  const load = useCallback(async () => {
    if (!id) return
    setLoading(true)
    setError('')
    try {
      const result = await loadWithDemo(
        () => vulnerabilityApi.list(id, { runId, riskLevel: risk, verifyStatus: verify, keyword, page }),
        () => demoList(risk, verify, keyword, page),
      )
      setList(result.data)
      setDemo(result.demo)
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setLoading(false)
    }
  }, [id, runId, risk, verify, keyword, page])

  useEffect(() => {
    void load()
  }, [load, revision])

  const openDetail = async (item: VulnerabilitySummary) => {
    if (!id) return
    setSelectedId(item.id)
    setSelected(null)
    setDrawerLoading(true)
    setDetailDemo(false)
    try {
      const result = await loadWithDemo(
        () => vulnerabilityApi.detail(id, item.id),
        () => {
          const found = DEMO_VULNERABILITIES.find((vuln) => vuln.id === item.id)
          if (!found) throw new Error('未找到漏洞详情')
          return found
        },
      )
      setSelected(result.data)
      setDetailDemo(result.demo)
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setDrawerLoading(false)
    }
  }

  const closeDetail = () => {
    setSelectedId(null)
    setSelected(null)
    setDetailDemo(false)
  }

  const riskCounts = useMemo(() => {
    if (!demo && detail?.vulnerability_stats) return detail.vulnerability_stats.risk_levels
    const counts: Record<string, number> = { critical: 0, high: 0, medium: 0, low: 0, info: 0 }
    for (const item of list?.items ?? []) counts[item.risk_level] = (counts[item.risk_level] ?? 0) + 1
    return counts
  }, [list, demo, detail?.vulnerability_stats])

  const stageLabel = (stageId: number | null) => {
    if (!stageId) return '—'
    const stage = detail?.stages.find((item) => item.stage_id === stageId)
    return stage ? STAGE_LABELS[stage.stage_name] ?? stage.stage_name : STAGE_ID_LABELS[stageId] ?? `阶段 #${stageId}`
  }

  const totalPages = list ? Math.max(1, Math.ceil(list.total / list.page_size)) : 1

  if (detailLoading && !detail) {
    return (
      <main className="page-pad">
        <LoadingBlock text="正在加载项目与漏洞数据…" />
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
      <ProjectHeader project={detail} active="vulnerabilities" counts={detail.counts} runs={detail.runs} runId={runId} />

      <main className="page-pad">
        <div className="page-head" style={{ marginBottom: 14 }}>
          <div>
            <div className="flex items-center gap-8">
              <h1 className="page-title" style={{ fontSize: 20 }}>
                漏洞
              </h1>
              {demo && <DemoPill />}
            </div>
            <div className="page-subtitle">
              当前轮次：第 {runId ?? detail.selected_run_id ?? detail.current_run_id} 轮 · 数据实时更新
            </div>
          </div>
          <div className="role-tag-list">
            {RISK_SUMMARY.map((item) => (
              <span
                key={item.key}
                className="chip"
                style={{ color: item.color, background: item.background, padding: '4px 9px' }}
              >
                <span style={{ width: 6, height: 6, borderRadius: 999, background: 'currentColor' }} />
                {item.label} {riskCounts[item.key] ?? 0}
              </span>
            ))}
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
              placeholder="搜索编号 / 标题 / 文件路径"
            />
          </div>
          <select
            className="select filter-select"
            value={risk}
            onChange={(event) => {
              setRisk(event.target.value as RiskLevel | '')
              setPage(1)
            }}
          >
            {RISK_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <select
            className="select filter-select"
            value={verify}
            onChange={(event) => {
              setVerify(event.target.value as VerifyStatus | '')
              setPage(1)
            }}
          >
            {VERIFY_OPTIONS.map((option) => (
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
              setRisk('')
              setVerify('')
              setKeywordInput('')
              setKeyword('')
              setPage(1)
            }}
          >
            重置
          </button>
          <span className="filter-spacer" />
          <span className="muted" style={{ fontSize: 12 }}>
            共 {list?.total ?? 0} 条
          </span>
        </div>

        <div className="table-card">
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ width: 100 }}>漏洞编号</th>
                  <th>漏洞标题</th>
                  <th style={{ width: 100 }}>风险等级</th>
                  <th style={{ width: 110 }}>验证状态</th>
                  <th style={{ width: 300 }}>文件位置</th>
                  <th style={{ width: 110 }}>所属阶段</th>
                  <th style={{ width: 90 }}>操作</th>
                </tr>
              </thead>
              <tbody>
                {loading &&
                  Array.from({ length: 5 }, (_, index) => (
                    <tr key={`vuln-skeleton-${index}`}>
                      <td><div className="skeleton" style={{ width: 70 }} /></td>
                      <td><div className="skeleton" style={{ width: 220 }} /></td>
                      <td><div className="skeleton" style={{ width: 52, height: 20, borderRadius: 999 }} /></td>
                      <td><div className="skeleton" style={{ width: 58, height: 20, borderRadius: 999 }} /></td>
                      <td><div className="skeleton" style={{ width: 240 }} /></td>
                      <td><div className="skeleton" style={{ width: 60 }} /></td>
                      <td><div className="skeleton" style={{ width: 60, marginLeft: 'auto' }} /></td>
                    </tr>
                  ))}

                {!loading &&
                  list?.items.map((item) => (
                    <tr key={item.id}>
                      <td className="mono" style={{ fontSize: 12, fontWeight: 500 }}>
                        {item.vuln_code}
                      </td>
                      <td>
                        <div className="cell-title">{item.vuln_title}</div>
                        <div className="cell-sub">
                          CVSS {item.cvss_score ?? '—'} · {stageLabel(item.stage_id)}
                        </div>
                      </td>
                      <td><RiskBadge level={item.risk_level} /></td>
                      <td><VerifyBadge status={item.verify_status} /></td>
                      <td className="mono muted" style={{ fontSize: 10 }}>
                        <span title={item.file_path ?? undefined}>{truncate(item.file_path ?? '—', 46)}</span>
                      </td>
                      <td className="muted" style={{ fontSize: 11 }}>{stageLabel(item.stage_id)}</td>
                      <td>
                        <div className="cell-actions">
                          <button type="button" className="link-action" onClick={() => void openDetail(item)}>
                            查看详情
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>

          {!loading && list && list.items.length === 0 && (
            <EmptyState
              icon="shield-check"
              title={keyword || risk || verify ? '没有符合条件的漏洞' : '本轮暂未发现漏洞'}
              description={
                keyword || risk || verify
                  ? '调整风险等级、验证状态或关键字后重试。'
                  : '评估仍在进行中，漏洞落库后会实时出现在这里。'
              }
            />
          )}

          {!loading && list && list.items.length > 0 && (
            <div className="pagination-bar">
              <span>共 {list.total} 条 · 每页 {list.page_size} 条</span>
              <div className="pager">
                <button type="button" disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label="上一页">
                  <Icon name="chevron-left" size={14} />
                </button>
                <button type="button" className="active" aria-current="page">{page}</button>
                <button type="button" disabled={page >= totalPages} onClick={() => setPage(page + 1)} aria-label="下一页">
                  <Icon name="chevron-right" size={14} />
                </button>
              </div>
            </div>
          )}
        </div>
      </main>

      {selectedId !== null && (
        <div className="drawer-overlay" role="presentation" onMouseDown={(event) => {
          if (event.target === event.currentTarget) closeDetail()
        }}>
          <aside className="drawer" role="dialog" aria-modal="true" aria-label="漏洞详情">
            <div className="drawer-head">
              <div className="drawer-head-top">
                <span className="drawer-title-row">
                  <span className="mono" style={{ color: 'var(--primary)', fontWeight: 600 }}>
                    {selected?.vuln_code ?? '漏洞详情'}
                  </span>
                  <span>漏洞详情</span>
                  {detailDemo && <DemoPill />}
                </span>
                <button type="button" className="icon-button" onClick={closeDetail} aria-label="关闭">
                  <Icon name="x" size={17} />
                </button>
              </div>
              <div className="drawer-title">{selected?.vuln_title ?? '加载中…'}</div>
              {selected && (
                <div className="drawer-badges">
                  <RiskBadge level={selected.risk_level} />
                  <VerifyBadge status={selected.verify_status} />
                  <span className="chip" style={{ color: 'var(--text-secondary)', background: 'var(--neutral-soft)' }}>
                    CVSS {selected.cvss_score ?? '—'}
                  </span>
                  <span className="chip" style={{ color: 'var(--text-secondary)', background: 'var(--neutral-soft)' }}>
                    {stageLabel(selected.stage_id)}
                  </span>
                </div>
              )}
            </div>

            <div className="drawer-body">
              {drawerLoading && <LoadingBlock text="正在加载漏洞详情…" />}
              {!drawerLoading && !selected && (
                <EmptyState compact icon="shield-alert" title="未找到漏洞详情" />
              )}
              {selected && (
                <>
                  {selected.verify_status === 'unverified' && (
                    <div className="alert alert-warning" style={{ marginBottom: 12 }}>
                      <Icon name="triangle-alert" size={13} />
                      <span>该漏洞尚未完成验证，结论需人工复核。</span>
                    </div>
                  )}
                  {selected.verify_status === 'false_positive' && (
                    <div className="alert alert-info" style={{ marginBottom: 12 }}>
                      <Icon name="info" size={13} />
                      <span>该漏洞已被判定为误报，不会进入攻击路径。</span>
                    </div>
                  )}

                  <div className="detail-section">
                    <div className="detail-section-title">
                      <Icon name="file-code" size={13} />
                      文件位置
                    </div>
                    <div className="detail-path">{selected.file_path ?? '—'}</div>
                  </div>

                  <DetailText icon="file-text" title="影响说明" text={selected.impact_text} />
                  <DetailText icon="zap" title="触发条件" text={selected.condition_text} />
                  <DetailCode icon="terminal" title="证据内容" text={selected.evidence_text} />
                  <DetailSteps text={selected.reproduce_steps_text} />
                  <DetailCode icon="code" title="验证代码" text={selected.verify_code_text} />
                </>
              )}
            </div>

            <div className="drawer-foot">
              <Link className="btn-link" to={`/projects/${detail.id}/attack-paths${runId ? `?run_id=${runId}` : ''}`}>
                <Icon name="route" size={13} />
                查看攻击路径
              </Link>
              <button type="button" className="btn btn-secondary btn-sm" onClick={closeDetail}>
                关闭
              </button>
            </div>
          </aside>
        </div>
      )}
    </>
  )
}

function DetailText({ icon, title, text }: { icon: 'file-text' | 'zap'; title: string; text: string | null }) {
  return (
    <div className="detail-section">
      <div className="detail-section-title">
        <Icon name={icon} size={13} />
        {title}
      </div>
      <div className="detail-text">{text || '—'}</div>
    </div>
  )
}

function DetailCode({ icon, title, text }: { icon: 'terminal' | 'code'; title: string; text: string | null }) {
  return (
    <div className="detail-section">
      <div className="detail-section-title">
        <Icon name={icon} size={13} />
        {title}
      </div>
      {text ? <pre className="code-block">{text}</pre> : <div className="detail-text">—</div>}
    </div>
  )
}

function DetailSteps({ text }: { text: string | null }) {
  const lines = linesOf(text)
  return (
    <div className="detail-section">
      <div className="detail-section-title">
        <Icon name="list-ordered" size={13} />
        复现步骤
      </div>
      {lines.length === 0 ? (
        <div className="detail-text">—</div>
      ) : (
        <ol className="step-list">
          {lines.map((line, index) => (
            <li key={`${index}-${line.slice(0, 12)}`}>
              <span className="step-index">{index + 1}.</span>
              <span>{line.replace(/^\d+[.、]\s*/, '')}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
