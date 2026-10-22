import { Link } from 'react-router-dom'
import { EmptyState } from '../components/ui'
import { Icon } from '../components/Icon'

export default function NotFoundPage() {
  return (
    <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', padding: 24 }}>
      <div className="card" style={{ width: 480 }}>
        <EmptyState
          icon="search"
          title="页面不存在"
          description="请检查地址是否正确，或返回项目列表继续操作。"
          action={
            <Link className="btn btn-primary" to="/projects">
              <Icon name="arrow-left" size={14} />
              返回项目列表
            </Link>
          }
        />
      </div>
    </div>
  )
}
