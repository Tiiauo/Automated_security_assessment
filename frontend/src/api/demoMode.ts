import { ApiError } from './client'

/**
 * 开发期（或显式开启 VITE_DEMO_MODE=1）允许对尚未接入后端的子资源接口
 * 展示原型演示数据。生产构建默认关闭，避免把演示数据误当成真实评估结果。
 */
export const DEMO_ENABLED =
  import.meta.env.DEV || import.meta.env.VITE_DEMO_MODE === '1'

export function isMissingEndpoint(error: unknown): boolean {
  // FastAPI 未注册路由返回裸 404；业务资源的 40401 不会被误判。
  return error instanceof ApiError && error.status === 404 && error.code === 404
}

export type DemoResult<T> = { data: T; demo: boolean }

export async function loadWithDemo<T>(
  loader: () => Promise<T>,
  fallback: () => T | Promise<T>,
): Promise<DemoResult<T>> {
  try {
    return { data: await loader(), demo: false }
  } catch (error) {
    if (DEMO_ENABLED && isMissingEndpoint(error)) {
      return { data: await fallback(), demo: true }
    }
    throw error
  }
}
