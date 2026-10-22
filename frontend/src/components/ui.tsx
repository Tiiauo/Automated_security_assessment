import type { ReactNode } from 'react'
import { Icon } from './Icon'
import type { IconName } from './Icon'
import type { ProjectStatus } from '../api/projects'
import type { RiskLevel, VerifyStatus } from '../api/vulnerabilities'

const PROJECT_STATUS_LABELS: Record<string, string> = {
  created: '已创建',
  running: '运行中',
  completed: '已完成',
  failed: '失败',
  stopped: '已停止',
}

const RISK_LABELS: Record<RiskLevel, string> = {
  critical: '严重',
  high: '高危',
  medium: '中危',
  low: '低危',
  info: '提示',
}

const VERIFY_LABELS: Record<VerifyStatus, string> = {
  pending: '待验证',
  verified: '已验证',
  unverified: '未验证',
  false_positive: '误报',
}

const VERIFY_CLASS: Record<VerifyStatus, string> = {
  pending: 'badge-pending',
  verified: 'badge-verified',
  unverified: 'badge-unverified',
  false_positive: 'badge-false-positive',
}

const STAGE_STATUS_LABELS: Record<string, string> = {
  pending: '等待中',
  running: '执行中',
  success: '成功',
  failed: '失败',
  stopped: '已停止',
  skipped: '已跳过',
}

export function StatusBadge({ status, dot = true }: { status: ProjectStatus | string; dot?: boolean }) {
  return (
    <span className={`badge badge-${status}`}>
      {dot && <span className="dot" />}
      {PROJECT_STATUS_LABELS[status] ?? status}
    </span>
  )
}

export function RiskBadge({ level }: { level: RiskLevel }) {
  return <span className={`badge badge-${level}`}>{RISK_LABELS[level] ?? level}</span>
}

export function VerifyBadge({ status }: { status: VerifyStatus }) {
  return (
    <span className={`badge ${VERIFY_CLASS[status] ?? 'badge-pending'}`}>
      {VERIFY_LABELS[status] ?? status}
    </span>
  )
}

export function StageStatusBadge({ status }: { status: string }) {
  return (
    <span className={`badge badge-${status}`}>
      {STAGE_STATUS_LABELS[status] ?? status}
    </span>
  )
}

export function WorkerStatusText({ status }: { status: string }) {
  const color =
    status === 'running'
      ? 'var(--primary)'
      : status === 'success'
        ? 'var(--success)'
        : status === 'failed'
          ? 'var(--danger)'
          : 'var(--neutral)'
  const label =
    status === 'running' ? '执行中' : status === 'success' ? '成功' : status === 'failed' ? '失败' : '空闲'
  return (
    <span className="role-status" style={{ color }}>
      {label}
    </span>
  )
}

export function DemoPill({ title = '当前为原型演示数据，后端接口接入后自动切换为真实数据' }: { title?: string }) {
  return (
    <span className="demo-pill" title={title}>
      <Icon name="info" size={11} />
      演示数据
    </span>
  )
}

export function Spinner({ size = 16 }: { size?: number }) {
  return <Icon className="spinner" name="loader-circle" size={size} />
}

export function LoadingBlock({ text = '加载中…' }: { text?: string }) {
  return (
    <div className="loading-block">
      <Spinner />
      <span>{text}</span>
    </div>
  )
}

type EmptyStateProps = {
  icon?: IconName
  title: string
  description?: ReactNode
  action?: ReactNode
  compact?: boolean
}

export function EmptyState({ icon = 'inbox', title, description, action, compact }: EmptyStateProps) {
  return (
    <div className={compact ? 'empty-state compact' : 'empty-state'}>
      <div className="empty-icon">
        <Icon name={icon} size={30} />
      </div>
      <div className="empty-title">{title}</div>
      {description && <div className="empty-desc">{description}</div>}
      {action}
    </div>
  )
}

type ConfirmDialogProps = {
  open: boolean
  title: string
  description: ReactNode
  confirmLabel?: string
  cancelLabel?: string
  tone?: 'danger' | 'warning' | 'primary'
  busy?: boolean
  onConfirm: () => void
  onClose: () => void
  children?: ReactNode
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = '确认',
  cancelLabel = '取消',
  tone = 'danger',
  busy = false,
  onConfirm,
  onClose,
  children,
}: ConfirmDialogProps) {
  if (!open) return null
  const icon: IconName = tone === 'danger' ? 'trash-2' : tone === 'warning' ? 'triangle-alert' : 'info'
  return (
    <div
      className="modal-overlay"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) onClose()
      }}
    >
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-head">
          <div className={`modal-icon ${tone}`}>
            <Icon name={icon} size={17} />
          </div>
          <div className="modal-title">{title}</div>
        </div>
        <div className="modal-desc">{description}</div>
        {children}
        <div className="modal-foot">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy} autoFocus>
            {cancelLabel}
          </button>
          <button
            type="button"
            className={tone === 'danger' ? 'btn btn-danger' : 'btn btn-primary'}
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? '处理中…' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

type PageHeadProps = {
  title: string
  subtitle?: ReactNode
  actions?: ReactNode
}

export function PageHead({ title, subtitle, actions }: PageHeadProps) {
  return (
    <div className="page-head">
      <div>
        <h1 className="page-title">{title}</h1>
        {subtitle && <div className="page-subtitle">{subtitle}</div>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  )
}
