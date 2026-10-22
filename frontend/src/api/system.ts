import { request } from './client'

export type CurrentUser = {
  id: number
  username: string
  role: 'user' | 'admin'
}

export type SystemStatus = { initialized: boolean }

export type InitResult = {
  admin_user_id: number
  demo_username: string | null
  demo_password: string | null
}

export type LoginResult = {
  user: CurrentUser
  expires_at: string
}

export type UserItem = CurrentUser & {
  status: 'active' | 'disabled'
  created_at: string | null
}

export type UserList = {
  items: UserItem[]
  total: number
  page: number
  page_size: number
}

export type LlmTestResult = {
  url_ok: boolean
  model_ok: boolean
  auth_ok: boolean
  tools_ok: boolean
  detail: string
}

export type ConfigMap = Record<string, string>

export const systemApi = {
  status: () => request<SystemStatus>('/api/system/status'),

  init: (username: string, password: string, createDemoUser: boolean) =>
    request<InitResult>('/api/system/init', {
      method: 'POST',
      body: { username, password, create_demo_user: createDemoUser },
    }),

  login: (username: string, password: string) =>
    request<LoginResult>('/api/system/login', {
      method: 'POST',
      body: { username, password },
    }),

  logout: () => request<{ logged_out: boolean }>('/api/system/logout', { method: 'POST' }),

  getConfig: () => request<ConfigMap>('/api/system/config'),

  updateConfig: (values: ConfigMap) =>
    request<ConfigMap>('/api/system/config', { method: 'PUT', body: values }),

  testLlm: (payload: { base_url?: string; model?: string; api_key?: string }) =>
    request<LlmTestResult>('/api/system/config/test-llm', { method: 'POST', body: payload }),

  listUsers: (page: number, pageSize = 20) =>
    request<UserList>(`/api/system/users?page=${page}&page_size=${pageSize}`),

  createUser: (username: string, password: string) =>
    request<{ user_id: number; username: string }>('/api/system/users', {
      method: 'POST',
      body: { username, password, role: 'user' },
    }),

  setUserStatus: (userId: number, status: 'active' | 'disabled') =>
    request<{ user_id: number; status: string }>(`/api/system/users/${userId}`, {
      method: 'PATCH',
      body: { status },
    }),

  deleteUser: (userId: number) =>
    request<{ user_id: number; deleted: boolean }>(`/api/system/users/${userId}`, {
      method: 'DELETE',
    }),
}
