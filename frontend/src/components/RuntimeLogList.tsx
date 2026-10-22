import { useEffect, useRef, useState } from 'react'
import type { RuntimeLog } from '../api/monitor'
import { formatClock } from '../utils/format'

const ROW_HEIGHT = 24

export default function RuntimeLogList({ logs, paused }: { logs: RuntimeLog[]; paused: boolean }) {
  const ref = useRef<HTMLDivElement>(null)
  const [top, setTop] = useState(0)
  const [height, setHeight] = useState(300)
  useEffect(() => {
    const element = ref.current
    if (!element) return
    const observer = new ResizeObserver(() => setHeight(element.clientHeight))
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  useEffect(() => {
    if (ref.current && !paused) ref.current.scrollTop = ref.current.scrollHeight
  }, [logs, paused])
  const start = Math.max(0, Math.min(logs.length - 1, Math.floor(top / ROW_HEIGHT) - 5))
  const visible = logs.slice(start, start + Math.ceil(height / ROW_HEIGHT) + 10)
  return <div ref={ref} className="log-list" role="log" aria-label="实时运行日志" tabIndex={0} onScroll={(event) => setTop(event.currentTarget.scrollTop)}>
    {logs.length === 0 ? <p>暂无运行日志</p> : <div style={{ height: logs.length * ROW_HEIGHT, position: 'relative' }}>
      {visible.map((log, index) => <div className={`log-line ${log.log_level}`} key={log.id} style={{ position: 'absolute', top: (start + index) * ROW_HEIGHT, width: '100%', height: ROW_HEIGHT }}>
        <span className="log-time">{formatClock(log.created_at)}</span>
        <span className="log-level">{log.log_level.toUpperCase()}</span>
        <span className="log-source">{log.stage_id ? `stage-${log.stage_id}` : 'system'}</span>
        <span className="log-msg" title={log.log_content} style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{log.log_content}</span>
      </div>)}
    </div>}
  </div>
}
