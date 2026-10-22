import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { systemApi } from '../api/system'
import { useAuth } from '../auth/AuthContext'
import { Icon } from './Icon'

function breadcrumbFor(pathname: string): string {
  if (pathname === '/projects') return '项目管理 / 项目列表'
  if (pathname === '/projects/new') return '项目管理 / 新建项目'
  if (/^\/projects\/\d+$/.test(pathname)) return '项目管理 / 项目详情'
  if (/^\/projects\/\d+\/monitor$/.test(pathname)) return '项目管理 / 实时监控'
  if (/^\/projects\/\d+\/vulnerabilities$/.test(pathname)) return '项目管理 / 漏洞'
  if (/^\/projects\/\d+\/attack-paths$/.test(pathname)) return '项目管理 / 攻击路径'
  if (/^\/projects\/\d+\/report$/.test(pathname)) return '项目管理 / 报告'
  if (pathname === '/settings') return '系统设置 / 系统配置'
  return '自动化安全评估系统'
}

export default function AppLayout() {
  const { user, signOut } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const isProjects = location.pathname.startsWith('/projects')
  const isSettings = location.pathname.startsWith('/settings')
  const isAdmin = user?.role === 'admin'
  const displayName = user?.username ?? '用户'
  const roleLabel = isAdmin ? '管理员' : '普通用户'
  const initial = displayName.slice(0, 1).toUpperCase()

  const handleLogout = async () => {
    try {
      await systemApi.logout()
    } catch {
      // 会话已失效时仍然清理本地登录态
    }
    signOut()
    navigate('/login', { replace: true })
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <div className="brand-logo">
            <Icon name="shield-check" size={18} />
          </div>
          <div className="brand-text">
            <span className="brand-name">安全评估</span>
            <span className="brand-sub">AUTOMATED SECURITY REVIEW</span>
          </div>
        </div>

        <div className="nav-group-label">工作台</div>
        <Link className={isProjects ? 'nav-item active' : 'nav-item'} to="/projects">
          <Icon name="folder-kanban" size={17} />
          <span>项目管理</span>
        </Link>
        {isAdmin && (
          <Link className={isSettings ? 'nav-item active' : 'nav-item'} to="/settings">
            <Icon name="settings" size={17} />
            <span>系统配置</span>
          </Link>
        )}

        <div className="sidebar-spacer" />

        <div className="sidebar-user">
          <div className="avatar">{initial}</div>
          <div className="user-meta">
            <span className="user-name">{displayName}</span>
            <span className="user-role">{roleLabel}</span>
          </div>
          <button
            type="button"
            className="icon-button"
            onClick={() => void handleLogout()}
            title="退出登录"
            aria-label="退出登录"
          >
            <Icon name="log-out" size={15} />
          </button>
        </div>
      </aside>

      <div className="app-main">
        <header className="topbar">
          <div className="breadcrumb">
            <Icon name="house" size={14} />
            <span>{breadcrumbFor(location.pathname)}</span>
          </div>
          <div className="topbar-actions">
            <span className="status-pill">
              <span className="dot" />
              服务运行正常
            </span>
            <button type="button" className="icon-button" title="通知" aria-label="通知">
              <Icon name="bell" size={18} />
            </button>
            <span style={{ fontSize: 13, fontWeight: 500 }}>{displayName}</span>
          </div>
        </header>

        <main className="app-content">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
