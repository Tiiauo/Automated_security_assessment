import { useCallback, useEffect, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { ApiError } from '../api/client'
import { adminApi } from '../api/admin'
import type {
  CleanupProject,
  SandboxItem,
  SandboxList,
  SystemLogList,
  SystemResourceSummary,
} from '../api/admin'
import { DEMO_SANDBOXES, DEMO_SYSTEM_LOGS, DEMO_SYSTEM_RESOURCES } from '../api/demo'
import { loadWithDemo } from '../api/demoMode'
import { projectApi } from '../api/projects'
import { systemApi } from '../api/system'
import type { ConfigMap, LlmTestResult, UserItem, UserList } from '../api/system'
import { useAuth } from '../auth/AuthContext'
import { Icon } from '../components/Icon'
import { ConfirmDialog, DemoPill, EmptyState, LoadingBlock, PageHead } from '../components/ui'
import { formatTime } from '../utils/format'

type Tab = 'config' | 'users' | 'sandboxes' | 'system'
type FieldType = 'text' | 'number' | 'password' | 'boolean' | 'select'

type FieldDef = {
  key: string
  label: string
  type: FieldType
  hint?: string
  step?: string
  disabled?: boolean
  wide?: boolean
  options?: { value: string; label: string }[]
}

type ConfigSection = { title: string; desc: string; fields: FieldDef[] }

type PendingConfirm =
  | { kind: 'user'; user: UserItem }
  | { kind: 'delete-user'; user: UserItem }
  | { kind: 'sandbox'; sandbox: SandboxItem }
  | { kind: 'cleanup'; project: CleanupProject }
  | null

const ENV_SECTION: ConfigSection = {
  title: '隔离环境',
  desc: 'Docker 容器运行参数与安全基线',
  fields: [
    {
      key: 'sandbox.type',
      label: '隔离环境类型',
      type: 'select',
      options: [{ value: 'docker', label: 'Docker' }],
      disabled: true,
    },
    {
      key: 'sandbox.source_mount_mode',
      label: '源码挂载模式',
      type: 'select',
      options: [{ value: 'ro', label: 'ro（只读）' }],
      disabled: true,
    },
    { key: 'sandbox.image', label: '基础镜像', type: 'text', wide: true },
    {
      key: 'sandbox.allowed_source_root',
      label: '允许的源码根目录',
      type: 'text',
      wide: true,
      hint: '多个根目录用英文逗号分隔；每项必须是绝对路径',
    },
    { key: 'sandbox.cpu_limit', label: 'CPU 上限（核）', type: 'number', step: '0.5' },
    { key: 'sandbox.memory_limit_mb', label: '内存上限（MB）', type: 'number' },
    { key: 'sandbox.network_enabled', label: '允许容器访问外网', type: 'boolean' },
  ],
}

const GIT_SECTION: ConfigSection = {
  title: '源码与 Git',
  desc: '白名单与只读凭据，敏感项加密存储',
  fields: [
    {
      key: 'git.allowed_hosts',
      label: 'Git 主机白名单',
      type: 'text',
      hint: '逗号分隔，例如 git.example.com；留空表示不允许拉取',
    },
    {
      key: 'git.credential',
      label: '仓库只读凭据',
      type: 'password',
      hint: '保持掩码表示不修改',
    },
    { key: 'limit.max_source_size_gb', label: '源码体积上限（GB）', type: 'number' },
    { key: 'limit.max_source_files', label: '源码文件数上限', type: 'number' },
  ],
}

const LIMIT_SECTION: ConfigSection = {
  title: '超时、并发与保留',
  desc: '阶段与角色任务的执行边界',
  fields: [
    { key: 'timeout.stage_seconds', label: '阶段超时（秒）', type: 'number' },
    { key: 'timeout.worker_seconds', label: '角色任务超时（秒）', type: 'number' },
    { key: 'timeout.command_seconds', label: '单条命令超时（秒）', type: 'number' },
    { key: 'limit.max_concurrent_projects', label: '最大并发项目数', type: 'number' },
    { key: 'retention.log_days', label: '日志保留天数', type: 'number' },
    { key: 'retention.resource_days', label: '资源记录保留天数', type: 'number' },
    { key: 'monitor.resource_interval_seconds', label: '资源采样周期（秒）', type: 'number' },
  ],
}

const MODEL_SECTION: ConfigSection = {
  title: '模型配置',
  desc: 'OpenAI 兼容协议 · 原生 function calling',
  fields: [
    { key: 'llm.base_url', label: '服务地址', type: 'text', wide: true },
    { key: 'llm.model', label: '模型名称', type: 'text', wide: true },
    {
      key: 'llm.api_key',
      label: 'API Key',
      type: 'password',
      wide: true,
      hint: '密钥加密存储，接口仅返回掩码值',
    },
    { key: 'llm.timeout_seconds', label: '调用超时（秒）', type: 'number' },
    {
      key: 'llm.max_tokens',
      label: '输出上限（token）',
      type: 'number',
      hint: '默认 32768；须在模型支持范围内，思考模式包含推理 token',
    },
    { key: 'llm.max_retries', label: '最大重试', type: 'number' },
    { key: 'llm.max_turns', label: '工具轮次', type: 'number' },
    { key: 'llm.thinking_enabled', label: '思考模式', type: 'boolean' },
  ],
}

const TABS: { key: Tab; label: string }[] = [
  { key: 'config', label: '运行配置' },
  { key: 'users', label: '用户管理' },
  { key: 'sandboxes', label: '隔离环境维护' },
  { key: 'system', label: '系统资源与日志' },
]

const SANDBOX_LABELS: Record<string, string> = {
  running: '运行中',
  stopped: '已停止',
  failed: '异常',
}

const LOG_LEVEL_CLASS: Record<string, string> = {
  info: 'badge-info',
  warning: 'badge-warning',
  error: 'badge-critical',
  debug: 'badge-pending',
}

function messageOf(error: unknown): string {
  return error instanceof ApiError ? error.message : '网络异常，请稍后重试'
}

type ConfirmCopy = {
  title: string
  description: string
  confirmLabel: string
  tone: 'warning' | 'danger'
}

function confirmCopy(pending: PendingConfirm): ConfirmCopy {
  switch (pending?.kind) {
    case 'user':
      return {
        title: '禁用用户',
        description: `确定禁用用户「${pending.user.username}」？该用户全部会话将立即失效。`,
        confirmLabel: '确认禁用',
        tone: 'warning',
      }
    case 'delete-user':
      return {
        title: '删除用户',
        description: `确定删除用户「${pending.user.username}」？该操作不可撤销，全部会话将立即失效；名下仍有项目时无法删除。`,
        confirmLabel: '确认删除',
        tone: 'danger',
      }
    case 'sandbox':
      return {
        title: '销毁隔离环境',
        description: `确定强制销毁隔离环境「${pending.sandbox.sandbox_id}」？异常容器将被立即清理。`,
        confirmLabel: '确认销毁',
        tone: 'danger',
      }
    case 'cleanup':
      return {
        title: '重试删除项目',
        description: `确定重试删除项目「${pending.project.project_name}」？将再次销毁残留环境并清理全部轮次目录。`,
        confirmLabel: '重试删除',
        tone: 'danger',
      }
    default:
      return { title: '', description: '', confirmLabel: '确认', tone: 'danger' }
  }
}

export default function SettingsPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'

  const [tab, setTab] = useState<Tab>('config')
  const [draft, setDraft] = useState<ConfigMap>({})
  const [configLoading, setConfigLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<LlmTestResult | null>(null)

  const [users, setUsers] = useState<UserList | null>(null)
  const [usersLoading, setUsersLoading] = useState(false)
  const [newUser, setNewUser] = useState({ username: '', password: '' })
  const [creating, setCreating] = useState(false)

  const [sandboxes, setSandboxes] = useState<SandboxList | null>(null)
  const [sandboxLoading, setSandboxLoading] = useState(false)
  const [sandboxDemo, setSandboxDemo] = useState(false)

  const [systemResources, setSystemResources] = useState<SystemResourceSummary | null>(null)
  const [systemLogs, setSystemLogs] = useState<SystemLogList | null>(null)
  const [systemLoading, setSystemLoading] = useState(false)
  const [systemDemo, setSystemDemo] = useState(false)
  const [systemPage, setSystemPage] = useState(1)

  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [pending, setPending] = useState<PendingConfirm>(null)
  const [confirmBusy, setConfirmBusy] = useState(false)

  const loadConfig = useCallback(async () => {
    setConfigLoading(true)
    setError('')
    try {
      setDraft(await systemApi.getConfig())
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setConfigLoading(false)
    }
  }, [])

  const loadUsers = useCallback(async (targetPage: number) => {
    setUsersLoading(true)
    setError('')
    try {
      setUsers(await systemApi.listUsers(targetPage))
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setUsersLoading(false)
    }
  }, [])

  const loadSandboxes = useCallback(async () => {
    setSandboxLoading(true)
    setError('')
    try {
      const result = await loadWithDemo(
        () => adminApi.sandboxes(),
        () => DEMO_SANDBOXES,
      )
      setSandboxes(result.data)
      setSandboxDemo(result.demo)
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setSandboxLoading(false)
    }
  }, [])

  const loadSystem = useCallback(async (targetPage: number) => {
    setSystemLoading(true)
    setError('')
    try {
      const [resources, logs] = await Promise.all([
        loadWithDemo(() => adminApi.resources(), () => DEMO_SYSTEM_RESOURCES),
        loadWithDemo(
          () => adminApi.logs({ page: targetPage, pageSize: 20 }),
          () => ({ ...DEMO_SYSTEM_LOGS, page: targetPage }),
        ),
      ])
      setSystemResources(resources.data)
      setSystemLogs(logs.data)
      setSystemDemo(resources.demo || logs.demo)
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setSystemLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!isAdmin) return
    void loadConfig()
    void loadUsers(1)
  }, [isAdmin, loadConfig, loadUsers])

  useEffect(() => {
    if (!isAdmin) return
    if (tab === 'sandboxes') void loadSandboxes()
    if (tab === 'system') void loadSystem(systemPage)
  }, [isAdmin, tab, systemPage, loadSandboxes, loadSystem])

  const updateField = (key: string, value: string) => {
    setDraft((previous) => ({ ...previous, [key]: value }))
  }

  const handleSave = async (event: FormEvent) => {
    event.preventDefault()
    setSaving(true)
    setError('')
    setNotice('')
    try {
      const data = await systemApi.updateConfig(draft)
      setDraft(data)
      setNotice('配置已保存，下次启动任务时生效')
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setSaving(false)
    }
  }

  const handleTestLlm = async () => {
    setTesting(true)
    setError('')
    setNotice('')
    setTestResult(null)
    try {
      setTestResult(
        await systemApi.testLlm({
          base_url: draft['llm.base_url'],
          model: draft['llm.model'],
          api_key: draft['llm.api_key'],
        }),
      )
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setTesting(false)
    }
  }

  const handleCreateUser = async (event: FormEvent) => {
    event.preventDefault()
    setCreating(true)
    setError('')
    setNotice('')
    try {
      await systemApi.createUser(newUser.username.trim(), newUser.password)
      setNewUser({ username: '', password: '' })
      setNotice('用户已创建')
      await loadUsers(1)
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setCreating(false)
    }
  }

  const handleConfirm = async () => {
    if (!pending) return
    setConfirmBusy(true)
    setError('')
    setNotice('')
    try {
      if (pending.kind === 'user') {
        await systemApi.setUserStatus(pending.user.id, 'disabled')
        setNotice('用户已禁用')
        await loadUsers(users?.page ?? 1)
      } else if (pending.kind === 'delete-user') {
        await systemApi.deleteUser(pending.user.id)
        setNotice(`用户「${pending.user.username}」已删除`)
        const page = users?.page ?? 1
        const lastItemOnPage = users?.items.length === 1
        await loadUsers(lastItemOnPage && page > 1 ? page - 1 : page)
      } else if (pending.kind === 'sandbox') {
        if (sandboxDemo) {
          setNotice('演示数据：未执行真实销毁操作')
        } else {
          await adminApi.destroySandbox(pending.sandbox.sandbox_id)
          setNotice('隔离环境已销毁')
          await loadSandboxes()
        }
      } else {
        if (sandboxDemo) {
          setNotice('演示数据：未执行真实删除操作')
        } else {
          await projectApi.remove(pending.project.project_id)
          setNotice('项目删除重试已提交')
          await loadSandboxes()
        }
      }
      setPending(null)
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setConfirmBusy(false)
    }
  }

  const renderField = (field: FieldDef) => {
    const value = draft[field.key] ?? ''
    if (field.type === 'boolean') {
      const on = value === 'true'
      return (
        <div className="flex items-center gap-8">
          <button
            type="button"
            className={on ? 'toggle on' : 'toggle'}
            aria-pressed={on}
            onClick={() => updateField(field.key, on ? 'false' : 'true')}
          >
            <span className="sr-only">{field.label}</span>
          </button>
          <span className="field-help">{on ? '开启' : '关闭'}</span>
        </div>
      )
    }
    if (field.type === 'select') {
      return (
        <select
          className="select"
          value={value}
          disabled={field.disabled}
          onChange={(event) => updateField(field.key, event.target.value)}
        >
          {field.options?.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      )
    }
    return (
      <input
        className="input"
        type={field.type}
        step={field.step}
        value={value}
        readOnly={field.disabled}
        onChange={(event) => updateField(field.key, event.target.value)}
      />
    )
  }

  if (!isAdmin) {
    return (
      <main className="page-pad">
        <PageHead title="系统配置" subtitle="维护系统运行参数、用户与隔离环境" />
        <div className="alert alert-error">
          <Icon name="triangle-alert" size={14} />
          <span>需要管理员权限。</span>
        </div>
      </main>
    )
  }

  return (
    <main className="page-pad">
      <PageHead
        title="系统配置"
        subtitle="维护隔离环境、源码限制、超时、并发与模型接入配置"
        actions={
          <span className="chip" style={{ color: 'var(--warning)', background: 'var(--warning-soft)', padding: '5px 10px' }}>
            <Icon name="info" size={12} />
            修改对已运行任务不生效，下次启动任务时应用
          </span>
        }
      />

      <div className="settings-tabs">
        {TABS.map((item) => (
          <button
            key={item.key}
            type="button"
            className={tab === item.key ? 'settings-tab active' : 'settings-tab'}
            onClick={() => setTab(item.key)}
          >
            {item.label}
          </button>
        ))}
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
        </div>
      )}

      {tab === 'config' && (
        <form onSubmit={handleSave} className="form-stack">
          {configLoading ? (
            <LoadingBlock text="正在加载配置…" />
          ) : (
            <div className="settings-grid">
              <div className="settings-column">
                {[ENV_SECTION, GIT_SECTION, LIMIT_SECTION].map((section) => (
                  <ConfigCard key={section.title} section={section} renderField={renderField} />
                ))}
              </div>
              <div className="settings-column">
                <ConfigCard section={MODEL_SECTION} renderField={renderField} />
                <section className="card">
                  <div className="card-head">
                    <div>
                      <div className="card-title">模型连接测试</div>
                      <div className="card-subtitle">使用已保存或当前填写的配置发起一次最小请求</div>
                    </div>
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      onClick={() => void handleTestLlm()}
                      disabled={testing || configLoading}
                    >
                      <Icon name="plug-zap" size={13} />
                      {testing ? '测试中…' : '测试连接'}
                    </button>
                  </div>
                  <div className="card-body">
                    {testResult ? (
                      <>
                        <div className="probe-list">
                          <ProbeRow label="服务地址" ok={testResult.url_ok} detail={testResult.url_ok ? '已连通' : '不可达'} />
                          <ProbeRow label="模型" ok={testResult.model_ok} detail={testResult.model_ok ? '模型存在' : '模型不可用'} />
                          <ProbeRow label="鉴权" ok={testResult.auth_ok} detail={testResult.auth_ok ? 'API Key 有效' : '鉴权失败'} />
                          <ProbeRow label="工具调用" ok={testResult.tools_ok} detail={testResult.tools_ok ? 'function calling 正常' : '不支持工具调用'} />
                        </div>
                        {testResult.detail && <p className="field-help mt-8">{testResult.detail}</p>}
                      </>
                    ) : (
                      <p className="field-help">
                        测试不会落库，也不会改变已保存配置。结果将依次展示地址、模型、鉴权与工具调用四项。
                      </p>
                    )}
                  </div>
                </section>
              </div>
            </div>
          )}

          <div className="form-footer">
            <span className="field-help">敏感项使用 AES-GCM 加密存储；接口返回掩码值。</span>
            <div className="form-actions">
              <button type="button" className="btn btn-secondary" onClick={() => void loadConfig()} disabled={configLoading}>
                重置
              </button>
              <button type="submit" className="btn btn-primary" disabled={saving || configLoading}>
                <Icon name="save" size={13} />
                {saving ? '保存中…' : '保存配置'}
              </button>
            </div>
          </div>
        </form>
      )}

      {tab === 'users' && (
        <div className="form-stack">
          <section className="card">
            <div className="card-head">
              <div>
                <div className="card-title">创建普通用户</div>
                <div className="card-subtitle">普通用户仅能查看自己创建的项目</div>
              </div>
            </div>
            <div className="card-body">
              <form onSubmit={handleCreateUser} className="user-create-form">
                <div className="form-grid">
                  <label className="field">
                    <span className="field-label">用户名</span>
                    <input
                      className="input"
                      value={newUser.username}
                      onChange={(event) => setNewUser({ ...newUser, username: event.target.value })}
                      required
                      minLength={3}
                      maxLength={64}
                      placeholder="例如：demo_user"
                    />
                  </label>
                  <label className="field">
                    <span className="field-label">初始密码</span>
                    <input
                      className="input"
                      type="password"
                      value={newUser.password}
                      onChange={(event) => setNewUser({ ...newUser, password: event.target.value })}
                      required
                      minLength={8}
                      placeholder="至少 8 位"
                    />
                  </label>
                </div>
                <div className="form-actions">
                  <button type="submit" className="btn btn-primary" disabled={creating}>
                    <Icon name="plus" size={13} />
                    {creating ? '创建中…' : '创建用户'}
                  </button>
                </div>
              </form>
            </div>
          </section>

          <section className="card">
            <div className="card-head">
              <div className="card-title">用户列表</div>
            </div>
            {usersLoading ? (
              <LoadingBlock />
            ) : users && users.items.length > 0 ? (
              <>
                <div className="table-scroll">
                  <table className="data-table user-table">
                    <thead>
                      <tr>
                        <th className="col-id">ID</th>
                        <th className="col-username">用户名</th>
                        <th className="col-role">角色</th>
                        <th className="col-status">状态</th>
                        <th className="col-time">创建时间</th>
                        <th className="col-actions">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {users.items.map((item) => (
                        <tr key={item.id}>
                          <td className="mono muted">{item.id}</td>
                          <td className="cell-title">{item.username}</td>
                          <td className="muted">{item.role === 'admin' ? '管理员' : '普通用户'}</td>
                          <td>
                            <span className={item.status === 'active' ? 'badge badge-completed' : 'badge badge-pending'}>
                              <span className="dot" />
                              {item.status === 'active' ? '启用' : '禁用'}
                            </span>
                          </td>
                          <td className="muted">{formatTime(item.created_at)}</td>
                          <td>
                            <div className="cell-actions">
                              <button
                                type="button"
                                className="link-action"
                                disabled={item.id === user?.id && item.status === 'active'}
                                onClick={() => {
                                  if (item.status === 'active') setPending({ kind: 'user', user: item })
                                  else {
                                    void systemApi
                                      .setUserStatus(item.id, 'active')
                                      .then(() => {
                                        setNotice('用户已启用')
                                        return loadUsers(users.page)
                                      })
                                      .catch((err) => setError(messageOf(err)))
                                  }
                                }}
                              >
                                {item.status === 'active' ? '禁用' : '启用'}
                              </button>
                              <button
                                type="button"
                                className="link-action danger"
                                disabled={item.id === user?.id}
                                title={item.id === user?.id ? '不能删除当前登录账号' : undefined}
                                onClick={() => setPending({ kind: 'delete-user', user: item })}
                              >
                                删除
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="pagination-bar">
                  <span>
                    第 {users.page} 页 · 共 {users.total} 个用户
                  </span>
                  <div className="pager">
                    <button
                      type="button"
                      disabled={users.page <= 1}
                      onClick={() => {
                        const next = users.page - 1
                        void loadUsers(next)
                      }}
                      aria-label="上一页"
                    >
                      <Icon name="chevron-left" size={14} />
                    </button>
                    <button type="button" className="active">{users.page}</button>
                    <button
                      type="button"
                      disabled={users.page * users.page_size >= users.total}
                      onClick={() => {
                        const next = users.page + 1
                        void loadUsers(next)
                      }}
                      aria-label="下一页"
                    >
                      <Icon name="chevron-right" size={14} />
                    </button>
                  </div>
                </div>
              </>
            ) : (
              <EmptyState compact icon="user" title="暂无用户" description="创建普通用户后，可在此启用或禁用账号。" />
            )}
            <div className="card-foot">
              <span className="field-help">禁用账号会立即撤销该用户全部会话；删除不可恢复，名下有项目的用户需先删除项目</span>
            </div>
          </section>
        </div>
      )}

      {tab === 'sandboxes' && (
        <div className="form-stack">
          <div className="flex items-center justify-between">
            <span className="field-help">
              查看隔离环境容器与待清理项目，异常环境可强制销毁。
            </span>
            <div className="flex items-center gap-8">
              {sandboxDemo && <DemoPill />}
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => void loadSandboxes()}>
                <Icon name="refresh-cw" size={13} />
                刷新
              </button>
            </div>
          </div>

          {sandboxLoading ? (
            <LoadingBlock text="正在加载隔离环境…" />
          ) : (
            <>
              <section className="card">
                <div className="card-head">
                  <div className="card-title">隔离环境容器</div>
                  <span className="field-help">{sandboxes?.items.length ?? 0} 个容器</span>
                </div>
                {sandboxes && sandboxes.items.length > 0 ? (
                  <div className="table-scroll">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>环境编号</th>
                          <th>关联项目</th>
                          <th style={{ width: 110 }}>状态</th>
                          <th style={{ width: 180 }}>创建时间</th>
                          <th style={{ width: 100 }}>操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {sandboxes.items.map((item) => (
                          <tr key={item.sandbox_id}>
                            <td className="mono">{item.sandbox_id}</td>
                            <td>
                              <div className="cell-title">{item.project_name}</div>
                              <div className="cell-sub">项目 #{item.project_id}</div>
                            </td>
                            <td>
                              <span className={`badge badge-${item.status === 'running' ? 'running' : item.status === 'failed' ? 'failed' : 'stopped'}`}>
                                <span className="dot" />
                                {SANDBOX_LABELS[item.status] ?? item.status}
                              </span>
                            </td>
                            <td className="muted">{formatTime(item.created_at)}</td>
                            <td>
                              <div className="cell-actions">
                                <button
                                  type="button"
                                  className="link-action danger"
                                  onClick={() => setPending({ kind: 'sandbox', sandbox: item })}
                                >
                                  销毁
                                </button>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <EmptyState compact icon="container" title="暂无隔离环境" description="项目启动后会创建独立容器。" />
                )}
              </section>

              <section className="card">
                <div className="card-head">
                  <div className="card-title">待清理项目</div>
                  <span className="field-help">目录清理失败的项目，可重试删除</span>
                </div>
                {sandboxes && sandboxes.cleanup_pending.length > 0 ? (
                  <div className="table-scroll">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>项目</th>
                          <th>清理错误</th>
                          <th style={{ width: 180 }}>最近尝试</th>
                          <th style={{ width: 110 }}>操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {sandboxes.cleanup_pending.map((project) => (
                          <tr key={project.project_id}>
                            <td>
                              <div className="cell-title">{project.project_name}</div>
                              <div className="cell-sub">项目 #{project.project_id}</div>
                            </td>
                            <td className="text-danger" style={{ fontSize: 11 }}>{project.cleanup_error ?? '—'}</td>
                            <td className="muted">{formatTime(project.updated_at)}</td>
                            <td>
                              <div className="cell-actions">
                                <button
                                  type="button"
                                  className="link-action"
                                  onClick={() => setPending({ kind: 'cleanup', project })}
                                >
                                  重试删除
                                </button>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <EmptyState compact icon="check" title="没有待清理项目" description="目录清理失败的项目会出现在这里。" />
                )}
              </section>
            </>
          )}
        </div>
      )}

      {tab === 'system' && (
        <div className="form-stack">
          <div className="flex items-center justify-between">
            <span className="field-help">全系统资源消耗与系统级运行 / 审计日志。</span>
            <div className="flex items-center gap-8">
              {systemDemo && <DemoPill />}
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => void loadSystem(systemPage)}>
                <Icon name="refresh-cw" size={13} />
                刷新
              </button>
            </div>
          </div>

          {systemLoading ? (
            <LoadingBlock text="正在加载系统资源与日志…" />
          ) : (
            <>
              <div className="stat-grid">
                <div className="stat-card">
                  <div className="stat-head">
                    <span>运行中项目</span>
                    <Icon name="folder-kanban" size={15} />
                  </div>
                  <span className="stat-value">{systemResources?.running_projects ?? 0}</span>
                  <span className="stat-sub">当前并发执行的项目</span>
                </div>
                <div className="stat-card">
                  <div className="stat-head">
                    <span>CPU 总使用</span>
                    <Icon name="activity" size={15} />
                  </div>
                  <span className="stat-value">{systemResources?.cpu_usage ?? 0}%</span>
                  <span className="stat-sub">全系统采样汇总</span>
                </div>
                <div className="stat-card">
                  <div className="stat-head">
                    <span>内存总使用</span>
                    <Icon name="database" size={15} />
                  </div>
                  <span className="stat-value">{(systemResources?.memory_usage ?? 0).toLocaleString('zh-CN')} MB</span>
                  <span className="stat-sub">容器内存合计</span>
                </div>
                <div className="stat-card">
                  <div className="stat-head">
                    <span>Token 总量</span>
                    <Icon name="zap" size={15} />
                  </div>
                  <span className="stat-value">{(systemResources?.token_count ?? 0).toLocaleString('zh-CN')}</span>
                  <span className="stat-sub">模型调用累计</span>
                </div>
              </div>

              {systemResources && systemResources.projects.length > 0 && (
                <section className="card">
                  <div className="card-head">
                    <div className="card-title">项目资源排行</div>
                  </div>
                  <div className="table-scroll">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>项目</th>
                          <th style={{ width: 120 }}>CPU</th>
                          <th style={{ width: 150 }}>内存（MB）</th>
                          <th style={{ width: 160 }}>Token</th>
                        </tr>
                      </thead>
                      <tbody>
                        {systemResources.projects.map((project) => (
                          <tr key={project.project_id}>
                            <td>
                              <div className="cell-title">{project.project_name}</div>
                              <div className="cell-sub">项目 #{project.project_id}</div>
                            </td>
                            <td>{project.cpu_usage}%</td>
                            <td>{project.memory_usage.toLocaleString('zh-CN')}</td>
                            <td>{project.token_count.toLocaleString('zh-CN')}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              )}

              <section className="card">
                <div className="card-head">
                  <div className="card-title">系统运行与审计日志</div>
                  <span className="field-help">共 {systemLogs?.total ?? 0} 条</span>
                </div>
                {systemLogs && systemLogs.items.length > 0 ? (
                  <>
                    <div className="table-scroll">
                      <table className="data-table">
                        <thead>
                          <tr>
                            <th style={{ width: 180 }}>时间</th>
                            <th style={{ width: 100 }}>级别</th>
                            <th style={{ width: 120 }}>来源</th>
                            <th>内容</th>
                          </tr>
                        </thead>
                        <tbody>
                          {systemLogs.items.map((log) => (
                            <tr key={log.id}>
                              <td className="mono muted" style={{ fontSize: 11 }}>{formatTime(log.created_at)}</td>
                              <td>
                                <span className={`badge ${LOG_LEVEL_CLASS[log.log_level] ?? 'badge-info'}`}>
                                  {log.log_level.toUpperCase()}
                                </span>
                              </td>
                              <td className="muted">{log.source ?? 'system'}</td>
                              <td className="mono" style={{ fontSize: 11 }}>{log.log_content}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <div className="pagination-bar">
                      <span>
                        第 {systemLogs.page} 页 · 共 {systemLogs.total} 条
                      </span>
                      <div className="pager">
                        <button
                          type="button"
                          disabled={systemPage <= 1}
                          onClick={() => setSystemPage((value) => Math.max(1, value - 1))}
                          aria-label="上一页"
                        >
                          <Icon name="chevron-left" size={14} />
                        </button>
                        <button type="button" className="active">{systemPage}</button>
                        <button
                          type="button"
                          disabled={systemPage * systemLogs.page_size >= systemLogs.total}
                          onClick={() => setSystemPage((value) => value + 1)}
                          aria-label="下一页"
                        >
                          <Icon name="chevron-right" size={14} />
                        </button>
                      </div>
                    </div>
                  </>
                ) : (
                  <EmptyState compact icon="scroll-text" title="暂无系统日志" description="服务运行与审计事件会记录在这里。" />
                )}
              </section>
            </>
          )}
        </div>
      )}

      <ConfirmDialog
        open={pending !== null}
        {...confirmCopy(pending)}
        busy={confirmBusy}
        onClose={() => setPending(null)}
        onConfirm={() => void handleConfirm()}
      />
    </main>
  )
}

function ConfigCard({
  section,
  renderField,
}: {
  section: ConfigSection
  renderField: (field: FieldDef) => ReactNode
}) {
  return (
    <section className="card config-card">
      <div className="card-head">
        <div>
          <div className="card-title">{section.title}</div>
          <div className="card-subtitle">{section.desc}</div>
        </div>
      </div>
      <div className="card-body">
        <div className="config-grid">
          {section.fields.map((field) => (
            <label key={field.key} className="field" style={field.wide ? { gridColumn: '1 / -1' } : undefined}>
              <span className="field-label" title={field.key}>
                {field.label}
              </span>
              {renderField(field)}
              {field.hint && <span className="field-help">{field.hint}</span>}
            </label>
          ))}
        </div>
      </div>
    </section>
  )
}

function ProbeRow({ label, ok, detail }: { label: string; ok: boolean; detail: string }) {
  return (
    <div className={ok ? 'probe-row ok' : 'probe-row fail'}>
      <span className="probe-left">
        <Icon name={ok ? 'circle-check' : 'circle-x'} size={12} />
        {label}
      </span>
      <span>{detail}</span>
    </div>
  )
}
