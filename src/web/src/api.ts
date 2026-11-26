export type Source = 'sample' | 'robot' | 'simulation'
export type Kind = 'depth' | 'fusion' | 'splat'
export type SceneStatus = 'active' | 'archived'
export interface Account {
  account_id: string
  email: string
  team_id: string
  role: 'admin' | 'member'
}
export interface Scene {
  scene_id: string
  title: string
  target?: string | null
  source: Source
  created_at: string
  owner_id?: string
  status?: SceneStatus
}
export interface Frame {
  frame_id: string
  filename: string
  view_label: string
  image_url: string
  created_at: string
}
export interface UploadRecord {
  upload_id: string
  uploader_email: string
  view_label: string
  created_at: string
}
export interface Revision {
  revision_id: string
  version: number
  frame_ids: string[]
  created_at: string
}
export interface Job {
  job_id: string
  revision_id: string
  kind: Kind
  status: string
  created_at: string
  recipe_version: string
  run_number?: number
  error_code?: string | null
  error_message?: string | null
  registration?: {
    registered_images: number
    total_images: number
    unregistered_frame_ids: string[]
  } | null
  artifacts?: { filename: string; url: string }[]
}
export const sources: Record<Source, string> = {
  sample: '手动样例',
  robot: '球形机器人',
  simulation: '虚拟相机',
}
export const kinds: Record<Kind, string> = {
  depth: '单图深度',
  fusion: '多图点云',
  splat: '3DGS 重建',
}
export const views = ['正面', '左侧', '背面', '右侧', '顶部', '其他']

export const sessionExpired = 'workbench:session-expired'
let sessionVersion = 0

export class ApiError extends Error {
  constructor(public readonly code: string | undefined, message: string) {
    super(message)
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const version = sessionVersion
  let response: Response
  try {
    response = await fetch('/api' + path, options)
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new Error('无法连接后端，请检查 API 服务。')
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const detail = body?.detail
    const hint = body?.message ?? (Array.isArray(detail) ? detail.map((item) => item.msg).join('，') : detail)
    const code = typeof body?.code === 'string' ? body.code : undefined
    if (response.status === 401 && code === 'LOGIN_REQUIRED' && path !== '/auth/me'
        && !options?.signal?.aborted && version === sessionVersion) {
      window.dispatchEvent(new Event(sessionExpired))
    }
    throw new ApiError(code, typeof hint === 'string' ? hint : `请求失败（HTTP ${response.status}）`)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

function json(body: unknown): RequestInit {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }
}
const scenePath = (id: string) => '/scenes/' + encodeURIComponent(id)

export const api = {
  health: (signal?: AbortSignal) => request<{ status: string; workbench?: 'team' }>('/health', { signal }),
  me: (signal?: AbortSignal) => request<Account>('/auth/me', { signal }),
  async login(email: string, password: string) {
    const account = await request<Account>('/auth/login', json({ email, password }))
    sessionVersion++
    return account
  },
  async logout() {
    await request<void>('/auth/logout', { method: 'POST' })
    sessionVersion++
  },
  scenes: (signal?: AbortSignal) => request<Scene[]>('/scenes', { signal }),
  create: (title: string, target: string, source: Source) =>
    request<Scene>('/scenes', json({ title, target, source })),
  rename: (id: string, title: string) =>
    request<Scene>(scenePath(id), { ...json({ title }), method: 'PATCH' }),
  archive: (id: string) => request<Scene>(scenePath(id) + '/archive', { method: 'POST' }),
  restore: (id: string) => request<Scene>(scenePath(id) + '/restore', { method: 'POST' }),
  frames: (id: string, signal?: AbortSignal) =>
    request<Frame[]>(scenePath(id) + '/frames', { signal }),
  uploadHistory: (sceneId: string, frameId: string, signal?: AbortSignal) =>
    request<UploadRecord[]>(scenePath(sceneId) + '/frames/' + encodeURIComponent(frameId) + '/uploads', { signal }),
  upload: (id: string, file: File, view: string, capture: string) => {
    const body = new FormData()
    body.set('image', file)
    body.set('view_label', view)
    body.set('capture_id', capture)
    return request<Frame>(scenePath(id) + '/frames', { method: 'POST', body })
  },
  revisions: (id: string, signal?: AbortSignal) =>
    request<Revision[]>(scenePath(id) + '/revisions', { signal }),
  freeze: (id: string, frameIds: string[]) =>
    request<Revision>(scenePath(id) + '/revisions', json({ frame_ids: frameIds })),
  jobs: (id: string, signal?: AbortSignal) => request<Job[]>(scenePath(id) + '/jobs', { signal }),
  enqueue: (revisionId: string, kind: Kind, recipeVersion = 'v1') =>
    request<Job>('/jobs', json({ revision_id: revisionId, kind, recipe_version: recipeVersion })),
}

export const errorText = (error: unknown) =>
  error instanceof Error ? error.message : '请求失败，请重试。'
export function timeLabel(input: string) {
  const date = new Date(input)
  return Number.isNaN(+date)
    ? input
    : new Intl.DateTimeFormat('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      }).format(date)
}
