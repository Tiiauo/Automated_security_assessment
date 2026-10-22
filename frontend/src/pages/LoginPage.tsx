import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../api/client'
import { systemApi } from '../api/system'
import { useAuth } from '../auth/AuthContext'
import { Icon } from '../components/Icon'
import { Spinner } from '../components/ui'

type Mode = 'loading' | 'login' | 'init'

const FEATURES = [
  {
    icon: 'scan-search' as const,
    title: '环境检查与代码分析',
    desc: '识别语言栈与依赖，逐文件分析并产出候选漏洞',
  },
  {
    icon: 'shield-alert' as const,
    title: '漏洞验证与攻击路径',
    desc: '在隔离环境中构造验证代码，串联多步利用链',
  },
  {
    icon: 'file-text' as const,
    title: '可追溯的安全报告',
    desc: '汇总漏洞、路径与修复建议，生成 Markdown / HTML 报告',
  },
]

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : '网络异常，请稍后重试'
}

export default function LoginPage() {
  const [mode, setMode] = useState<Mode>('loading')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [createDemoUser, setCreateDemoUser] = useState(true)
  const [showPassword, setShowPassword] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const { user, signIn } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    if (user) {
      navigate('/projects', { replace: true })
    }
  }, [user, navigate])

  useEffect(() => {
    systemApi
      .status()
      .then((data) => setMode(data.initialized ? 'login' : 'init'))
      .catch((err) => {
        setError(errorMessage(err))
        setMode('login')
      })
  }, [])

  const handleInit = async (event: FormEvent) => {
    event.preventDefault()
    setError('')
    setNotice('')
    if (password !== confirmPassword) {
      setError('两次输入的密码不一致')
      return
    }
    setSubmitting(true)
    try {
      const result = await systemApi.init(username.trim(), password, createDemoUser)
      setMode('login')
      setPassword('')
      setConfirmPassword('')
      const demo =
        result.demo_username && result.demo_password
          ? `默认普通账号：${result.demo_username} / ${result.demo_password}`
          : ''
      setNotice(`系统初始化完成，请使用管理员账号登录。${demo}`)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  const handleLogin = async (event: FormEvent) => {
    event.preventDefault()
    setError('')
    setNotice('')
    setSubmitting(true)
    try {
      const result = await systemApi.login(username.trim(), password)
      signIn(result.user)
      navigate('/projects', { replace: true })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="login-page">
      <section className="login-brand">
        <div className="sidebar-brand" style={{ padding: 0, height: 'auto' }}>
          <div className="brand-logo">
            <Icon name="shield-check" size={21} />
          </div>
          <div className="brand-text">
            <span className="brand-name" style={{ fontSize: 16 }}>
              自动化安全评估系统
            </span>
            <span className="brand-sub">AUTOMATED SECURITY ASSESSMENT</span>
          </div>
        </div>

        <div className="login-hero">
          <span className="eyebrow">AI-POWERED SECURITY REVIEW</span>
          <h1 className="login-headline">{'把源码审查\n交给一支 AI 安全团队'}</h1>
          <p className="login-lead">
            接入源码项目，在 Docker 隔离环境中完成环境检查、代码分析、漏洞验证、攻击路径整理与报告生成。
          </p>
          <div className="feature-list">
            {FEATURES.map((feature) => (
              <div className="feature" key={feature.title}>
                <div className="feature-icon">
                  <Icon name={feature.icon} size={18} />
                </div>
                <div>
                  <div className="feature-title">{feature.title}</div>
                  <div className="feature-desc">{feature.desc}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="login-brand-footer">
          <span>隔离执行 · 数据不出域 · 全流程可追溯</span>
          <span>v1.5</span>
        </div>
      </section>

      <section className="login-panel">
        <div className="login-top">
          {mode === 'init' ? '初始化后将创建首个管理员账号' : '没有账号？请联系管理员开通'}
        </div>

        <div className="login-card">
          <div>
            <div className="login-icon">
              <Icon name={mode === 'init' ? 'shield-check' : 'lock'} size={22} />
            </div>
            <h2 className="login-title" style={{ marginTop: 14 }}>
              {mode === 'init' ? '初始化系统' : '欢迎回来'}
            </h2>
            <p className="login-subtitle">
              {mode === 'init'
                ? '首次使用需创建管理员账号，初始化完成后不可重复执行。'
                : '登录以继续管理安全评估项目'}
            </p>
          </div>

          {notice && (
            <div className="alert alert-success" style={{ marginBottom: 0 }}>
              <Icon name="circle-check" size={14} />
              <span>{notice}</span>
            </div>
          )}
          {error && (
            <div className="alert alert-error" style={{ marginBottom: 0 }}>
              <Icon name="triangle-alert" size={14} />
              <span>{error}</span>
            </div>
          )}

          {mode === 'loading' && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-secondary)', fontSize: 13 }}>
              <Spinner />
              正在检查系统状态…
            </div>
          )}

          {mode === 'init' && (
            <form className="form-stack" onSubmit={handleInit}>
              <div className="alert alert-warning" style={{ marginBottom: 0 }}>
                <Icon name="triangle-alert" size={14} />
                <span>系统尚未初始化，请创建管理员账号后登录。</span>
              </div>
              <label className="field">
                <span className="field-label">管理员用户名</span>
                <div className="input-wrap">
                  <span className="input-icon">
                    <Icon name="user" size={15} />
                  </span>
                  <input
                    className="input"
                    value={username}
                    onChange={(event) => setUsername(event.target.value)}
                    autoComplete="username"
                    required
                    minLength={3}
                    maxLength={64}
                  />
                </div>
              </label>
              <label className="field">
                <span className="field-label">密码</span>
                <div className="input-wrap">
                  <span className="input-icon">
                    <Icon name="lock" size={15} />
                  </span>
                  <input
                    className="input"
                    type={showPassword ? 'text' : 'password'}
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    autoComplete="new-password"
                    required
                    minLength={8}
                  />
                  <button
                    type="button"
                    className="input-action"
                    onClick={() => setShowPassword((previous) => !previous)}
                    aria-label={showPassword ? '隐藏密码' : '显示密码'}
                  >
                    <Icon name={showPassword ? 'eye-off' : 'eye'} size={15} />
                  </button>
                </div>
              </label>
              <label className="field">
                <span className="field-label">确认密码</span>
                <div className="input-wrap">
                  <span className="input-icon">
                    <Icon name="lock" size={15} />
                  </span>
                  <input
                    className="input"
                    type={showPassword ? 'text' : 'password'}
                    value={confirmPassword}
                    onChange={(event) => setConfirmPassword(event.target.value)}
                    autoComplete="new-password"
                    required
                    minLength={8}
                  />
                </div>
              </label>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={createDemoUser}
                  onChange={(event) => setCreateDemoUser(event.target.checked)}
                />
                <span>同时创建默认普通账号 demo_user</span>
              </label>
              <button type="submit" className="btn btn-primary btn-block" style={{ height: 44 }} disabled={submitting}>
                {submitting ? '初始化中…' : '初始化系统'}
                {!submitting && <Icon name="arrow-right" size={16} />}
              </button>
              <p className="field-help">
                密码至少 8 位，建议包含大小写字母、数字与符号。初始化完成后将自动创建演示普通账号 demo_user。
              </p>
            </form>
          )}

          {mode === 'login' && (
            <form className="form-stack" onSubmit={handleLogin}>
              <label className="field">
                <span className="field-label">用户名</span>
                <div className="input-wrap">
                  <span className="input-icon">
                    <Icon name="user" size={15} />
                  </span>
                  <input
                    className="input"
                    value={username}
                    onChange={(event) => setUsername(event.target.value)}
                    autoComplete="username"
                    required
                  />
                </div>
              </label>
              <label className="field">
                <span className="field-label">密码</span>
                <div className="input-wrap">
                  <span className="input-icon">
                    <Icon name="lock" size={15} />
                  </span>
                  <input
                    className="input"
                    type={showPassword ? 'text' : 'password'}
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    autoComplete="current-password"
                    required
                  />
                  <button
                    type="button"
                    className="input-action"
                    onClick={() => setShowPassword((previous) => !previous)}
                    aria-label={showPassword ? '隐藏密码' : '显示密码'}
                  >
                    <Icon name={showPassword ? 'eye-off' : 'eye'} size={15} />
                  </button>
                </div>
              </label>
              <button type="submit" className="btn btn-primary btn-block" style={{ height: 44 }} disabled={submitting}>
                {submitting ? '登录中…' : '登录'}
                {!submitting && <Icon name="arrow-right" size={16} />}
              </button>
              <p className="field-help">登录状态有效期 8 小时。连续 5 次失败将锁定 10 分钟。</p>
            </form>
          )}
        </div>

        <div className="login-bottom">
          <span>© 2026 自动化安全评估系统</span>
          <span>仅限授权人员访问与使用</span>
        </div>
      </section>
    </div>
  )
}
