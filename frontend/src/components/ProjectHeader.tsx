import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import type { Project, ProjectRun } from '../api/projects'
import { Icon } from './Icon'
import { StatusBadge } from './ui'

export type ProjectTab = 'overview' | 'monitor' | 'vulnerabilities' | 'attack-paths' | 'report'

type ProjectHeaderProps = {
  project: Pick<Project, 'id' | 'project_name' | 'project_status' | 'current_run_id'>
  active: ProjectTab
  counts?: { vulnerabilities?: number; attack_paths?: number }
  runs?: ProjectRun[]
  runId?: number | null
  onRunChange?: (runId: number) => void
  actions?: ReactNode
}

const TABS: { key: ProjectTab; label: string; path: string }[] = [
  { key: 'overview', label: '概览', path: '' },
  { key: 'monitor', label: '实时监控', path: '/monitor' },
  { key: 'vulnerabilities', label: '漏洞', path: '/vulnerabilities' },
  { key: 'attack-paths', label: '攻击路径', path: '/attack-paths' },
  { key: 'report', label: '报告', path: '/report' },
]

export default function ProjectHeader({
  project,
  active,
  counts,
  runs = [],
  runId,
  onRunChange,
  actions,
}: ProjectHeaderProps) {
  const selectedRun = runId ?? project.current_run_id ?? 0
  const suffix = runId ? `?run_id=${runId}` : ''
  const countFor = (key: ProjectTab) => {
    if (key === 'vulnerabilities') return counts?.vulnerabilities
    if (key === 'attack-paths') return counts?.attack_paths
    return undefined
  }

  return (
    <div className="project-head">
      <div className="project-title-row">
        <div className="project-title-group">
          <h1 className="project-name">{project.project_name}</h1>
          <StatusBadge status={project.project_status} />
          {runs.length > 0 && onRunChange ? (
            <select
              className="run-select"
              value={selectedRun}
              onChange={(event) => onRunChange(Number(event.target.value))}
              aria-label="选择执行轮次"
            >
              {runs.map((run) => (
                <option key={run.run_id} value={run.run_id}>
                  第 {run.run_id} 轮
                </option>
              ))}
            </select>
          ) : (
            <span className="run-select" style={{ display: 'inline-flex', alignItems: 'center' }}>
              第 {selectedRun || 1} 轮
            </span>
          )}
        </div>
        {actions && <div className="project-actions">{actions}</div>}
      </div>

      <nav className="project-tabs" aria-label="项目页面">
        {TABS.map((tab) => {
          const count = countFor(tab.key)
          return (
            <Link
              key={tab.key}
              to={`/projects/${project.id}${tab.path}${suffix}`}
              className={active === tab.key ? 'project-tab active' : 'project-tab'}
            >
              <span>{tab.label}</span>
              {typeof count === 'number' && <span className="tab-count">{count}</span>}
            </Link>
          )
        })}
        <span style={{ flex: 1 }} />
        <Link className="btn-link" to={`/projects/${project.id}/monitor${suffix}`}>
          <Icon name="activity" size={12} />
          实时状态
        </Link>
      </nav>
    </div>
  )
}
