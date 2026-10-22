export class ApiError extends Error {
  readonly code: number
  readonly status: number
  readonly data: unknown

  constructor(message: string, code: number, status: number, data?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.data = data
  }
}

type RequestOptions = {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown
}

type Envelope<T> = {
  code: number
  message: string
  data: T
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await fetch(path, {
    method: options.method ?? 'GET',
    credentials: 'include',
    headers: options.body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  })

  let payload: Envelope<T> | null = null
  try {
    payload = (await response.json()) as Envelope<T>
  } catch {
    payload = null
  }

  if (!response.ok || payload === null || payload.code !== 0) {
    if (response.status === 401) {
      window.dispatchEvent(new Event('auth:unauthorized'))
    }
    throw new ApiError(
      payload?.message ?? `请求失败（HTTP ${response.status}）`,
      payload?.code ?? response.status,
      response.status,
      payload?.data,
    )
  }

  return payload.data
}
