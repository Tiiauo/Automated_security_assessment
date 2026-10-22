function pad(value: number): string {
  return String(value).padStart(2, '0')
}

/** 接口返回带时区偏移的 ISO 8601，按浏览器本地时区展示为 YYYY-MM-DD HH:mm:ss。 */
export function formatTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
  )
}

/** 只展示时分秒（本地时区），用于日志与消息时间列。 */
export function formatClock(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

export function truncate(value: string, max = 48): string {
  return value.length > max ? `${value.slice(0, max)}…` : value
}
