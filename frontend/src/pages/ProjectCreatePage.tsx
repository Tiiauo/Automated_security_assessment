import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ApiError } from '../api/client'
import { projectApi } from '../api/projects'
import type { SourceType } from '../api/projects'
import { Icon } from '../components/Icon'
import { PageHead } from '../components/ui'

function messageOf(error: unknown): string {
  return error instanceof ApiError ? error.message : '网络异常，请稍后重试'
}

const SOURCE_OPTIONS: { value: SourceType; title: string; desc: string; icon: 'git-branch' | 'folder' }[] = [
  { value: 'git_repo', title: 'Git 仓库', desc: '从远程仓库拉取源码', icon: 'git-branch' },
  { value: 'local_path', title: '本地目录', desc: '接入白名单内的本地源码', icon: 'folder' },
]

const CHECK_ITEMS = [
  '源码路径位于允许的根目录内',
  'Git 主机已加入允许列表',
  '源码体积与文件数在限制内',
  '隔离环境资源配额已配置',
]

export default function ProjectCreatePage() {
  const [projectName, setProjectName] = useState('')
  const [sourceType, setSourceType] = useState<SourceType>('git_repo')
  const [sourcePath, setSourcePath] = useState('')
  const [taskContent, setTaskContent] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const navigate = useNavigate()

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setSubmitting(true)
    setError('')
    try {
      const result = await projectApi.create({
        project_name: projectName.trim(),
        source_type: sourceType,
        source_path: sourcePath.trim(),
        task_content: taskContent.trim(),
        sandbox_type: 'docker',
      })
      navigate(`/projects/${result.project_id}`)
    } catch (err) {
      setError(messageOf(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="page-pad">
      <PageHead
        title="新建项目"
        subtitle="填写项目信息并选择源码来源，创建后可启动自动化安全评估"
        actions={
          <Link className="btn btn-secondary" to="/projects">
            <Icon name="arrow-left" size={14} />
            返回列表
          </Link>
        }
      />

      {error && (
        <div className="alert alert-error">
          <Icon name="triangle-alert" size={14} />
          <span>{error}</span>
        </div>
      )}

      <div className="create-layout">
        <form className="card create-form" onSubmit={handleSubmit}>
          <div className="card-body">
            <div className="flex items-center justify-between mb-8">
              <span className="section-title">项目信息</span>
              <span className="flex items-center gap-6" style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                <Icon name="lock" size={12} />
                数据仅创建者与管理员可见
              </span>
            </div>

            <div className="field">
              <div className="flex items-center justify-between">
                <span className="field-label">
                  项目名称<span className="required">*</span>
                </span>
                <span className="field-count">{projectName.length} / 100</span>
              </div>
              <input
                className="input"
                value={projectName}
                onChange={(event) => setProjectName(event.target.value)}
                maxLength={100}
                required
                placeholder="例如：电商后台服务安全评估"
              />
              <span className="field-help">1~100 字符，去除首尾空格，同一创建者下不可重名。</span>
            </div>

            <div className="field">
              <span className="field-label">
                源码类型<span className="required">*</span>
              </span>
              <div className="segmented-cards">
                {SOURCE_OPTIONS.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    className={sourceType === option.value ? 'segmented-card active' : 'segmented-card'}
                    onClick={() => setSourceType(option.value)}
                  >
                    <span className="segmented-icon">
                      <Icon name={option.icon} size={16} />
                    </span>
                    <span className="segmented-text">
                      <span className="segmented-title">{option.title}</span>
                      <span className="segmented-desc">{option.desc}</span>
                    </span>
                    <span className="radio-dot" />
                  </button>
                ))}
              </div>
            </div>

            <div className="field">
              <span className="field-label">
                源码路径<span className="required">*</span>
              </span>
              <div className="input-wrap">
                <span className="input-icon">
                  <Icon name={sourceType === 'git_repo' ? 'git-branch' : 'folder'} size={15} />
                </span>
                <input
                  className="input"
                  value={sourcePath}
                  onChange={(event) => setSourcePath(event.target.value)}
                  maxLength={500}
                  required
                  placeholder={
                    sourceType === 'git_repo'
                      ? 'https://git.example.com/group/repo.git'
                      : '/data/allowed_sources/example-project'
                  }
                />
              </div>
              <span className="field-help">
                {sourceType === 'git_repo'
                  ? '仅支持 http(s) 或 SSH 远程地址，目标主机需在管理员配置的 git.allowed_hosts 白名单内。'
                  : '必须位于系统配置允许的源码根目录白名单（sandbox.allowed_source_root）内。'}
              </span>
            </div>

            <div className="field">
              <div className="flex items-center justify-between">
                <span className="field-label">
                  任务说明<span className="required">*</span>
                </span>
                <span className="field-count">{taskContent.length} / 5000</span>
              </div>
              <textarea
                className="textarea"
                value={taskContent}
                onChange={(event) => setTaskContent(event.target.value)}
                maxLength={5000}
                required
                placeholder="描述评估目标、关注的漏洞类型与验证范围"
              />
              <span className="field-help">作为角色任务说明的初始上下文，1~5000 字符。</span>
            </div>

            <div className="field">
              <span className="field-label">
                隔离环境类型<span className="required">*</span>
              </span>
              <div className="input-wrap">
                <span className="input-icon">
                  <Icon name="container" size={15} />
                </span>
                <input className="input" value="Docker" readOnly />
              </div>
              <span className="field-help">
                本期仅支持 Docker，容器以非特权用户运行、只读挂载源码并默认禁用外网。
              </span>
            </div>

            <div className="form-footer">
              <span className="field-help">创建后将进入项目详情页，可立即启动评估。</span>
              <div className="form-actions">
                <Link className="btn btn-secondary" to="/projects">
                  取消
                </Link>
                <button type="submit" className="btn btn-primary" disabled={submitting}>
                  {submitting ? '创建中…' : '创建并进入详情'}
                  {!submitting && <Icon name="arrow-right" size={14} />}
                </button>
              </div>
            </div>
          </div>
        </form>

        <aside className="aside-column">
          <section className="card card-body">
            <div className="flex items-center gap-8 mb-8">
              <Icon name="clipboard-check" size={17} style={{ color: 'var(--primary)' }} />
              <span className="section-title" style={{ fontSize: 14 }}>
                创建前请确认
              </span>
            </div>
            <div className="check-list">
              {CHECK_ITEMS.map((item) => (
                <div className="check-row" key={item}>
                  <Icon name="circle-check" size={15} />
                  <span>{item}</span>
                </div>
              ))}
            </div>
          </section>

          <section className="card card-body">
            <span className="section-title" style={{ fontSize: 14 }}>
              源码规模限制
            </span>
            <div className="number-pair mt-12">
              <div className="number-box">
                <strong>2 GB</strong>
                <span>体积上限</span>
              </div>
              <div className="number-box">
                <strong>200,000</strong>
                <span>文件数上限</span>
              </div>
            </div>
            <p className="field-help mt-12">超出限制时启动任务将失败，可在系统配置中调整。</p>
          </section>

          <section className="card card-body" style={{ background: 'var(--primary-soft)', borderColor: '#bfdbfe' }}>
            <div className="flex items-center gap-8">
              <Icon name="shield" size={16} style={{ color: 'var(--primary)' }} />
              <span className="section-title" style={{ fontSize: 13, color: 'var(--primary)' }}>
                安全隔离
              </span>
            </div>
            <p className="field-help mt-8" style={{ color: '#1e40af' }}>
              源码以只读方式挂载至 /src，容器丢弃全部 Capabilities，默认禁止外网访问。
            </p>
          </section>
        </aside>
      </div>
    </main>
  )
}
