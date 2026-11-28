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
  uploader_id?: string
}
export interface UploadRecord {
  upload_id: string
  uploader_email: string
  view_label: string
  created_at: string
  video_source?: VideoSource | null
}
export interface Revision {
  revision_id: string
  version: number
  frame_ids: string[]
  created_at: string
  video_sources?: Record<string, VideoSource[]>
}
export interface ExtractionParameters {
  start_seconds: number
  duration_seconds: number | null
  fps: number
  max_frames: number
}
export interface VideoSummary {
  video_id: string
  filename: string
  sha256: string
  original_url: string
  parameters: ExtractionParameters & { max_edge: number }
  ffmpeg_version: string
}
export type VideoSource = VideoSummary & { candidate_id: string; position: number }
export interface VideoPreview extends VideoSummary {
  candidates: {
    candidate_id: string
    position: number
    image_url: string
    width: number
    height: number
  }[]
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
export interface TeamJob extends Job {
  run_number: number
}
export const sources: Record<Source, string> = {
  sample: '手动样例',
  robot: '仿生采集平台',
  simulation: '虚拟相机',
}
export const kinds: Record<Kind, string> = {
  depth: '单图深度',
  fusion: '多图点云',
  splat: '3DGS 重建',
}
export const recipeLabel = (job: Job) => {
  if (job.kind === 'splat') {
    if (job.recipe_version === 'public-32-v1') return '公开 32 图验收'
    if (job.recipe_version === 'v1') return '普通重建'
  }
  return job.recipe_version
}
export const views = ['正面', '左侧', '背面', '右侧', '顶部', '其他']

export const sessionExpired = 'workbench:session-expired'
let sessionVersion = 0

export class ApiError extends Error {
  constructor(public readonly code: string | undefined, message: string) {
    super(message)
  }
}

type FailureBody = { detail?: string | { msg: string }[]; message?: string; code?: string } | null

function responseError(status: number, body: FailureBody, path: string, version: number, signal?: AbortSignal | null) {
  const detail = body?.detail
  const hint = body?.message ?? (Array.isArray(detail) ? detail.map((item) => item.msg).join('，') : detail)
  const code = typeof body?.code === 'string' ? body.code : undefined
  if (status === 401 && code === 'LOGIN_REQUIRED' && path !== '/auth/me'
      && !signal?.aborted && version === sessionVersion) {
    window.dispatchEvent(new Event(sessionExpired))
  }
  return new ApiError(code, typeof hint === 'string' ? hint : `请求失败（HTTP ${status}）`)
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
    throw responseError(response.status, await response.json().catch(() => null), path, version, options?.signal)
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
const framePath = (sceneId: string, frameId: string) => scenePath(sceneId) + '/frames/' + encodeURIComponent(frameId)
const videosPath = (id: string) => scenePath(id) + '/videos'
const videoPath = (id: string, videoId: string) => videosPath(id) + '/' + encodeURIComponent(videoId)

function uploadVideo(
  id: string, file: File, parameters: ExtractionParameters, progress: (value: number) => void, signal: AbortSignal,
) {
  const version = sessionVersion
  const query = new URLSearchParams({ filename: file.name })
  for (const [name, value] of Object.entries(parameters)) {
    if (value !== null) query.set(name, String(value))
  }
  const path = videosPath(id) + '?' + query
  return new Promise<VideoPreview>((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException('Upload aborted', 'AbortError'))
      return
    }
    const xhr = new XMLHttpRequest()
    const abort = () => xhr.abort()
    xhr.open('POST', '/api' + path)
    xhr.responseType = 'json'
    xhr.setRequestHeader('Content-Type', 'video/mp4')
    xhr.upload.onprogress = (event) => progress(Math.min(99, Math.floor(event.loaded / file.size * 100)))
    xhr.upload.onload = () => progress(100)
    xhr.onload = () => {
      if (xhr.status === 201 && xhr.response) resolve(xhr.response as VideoPreview)
      else reject(responseError(xhr.status, xhr.response, path, version, signal))
    }
    xhr.onerror = () => reject(new Error('无法连接后端，请检查 API 服务。'))
    xhr.onabort = () => reject(new DOMException('Upload aborted', 'AbortError'))
    xhr.onloadend = () => signal.removeEventListener('abort', abort)
    signal.addEventListener('abort', abort, { once: true })
    xhr.send(file)
  })
}

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
    request<UploadRecord[]>(framePath(sceneId, frameId) + '/uploads', { signal }),
  withdrawFrame: (sceneId: string, frameId: string) =>
    request<void>(framePath(sceneId, frameId), { method: 'DELETE' }),
  upload: (id: string, file: File, view: string, capture: string) => {
    const body = new FormData()
    body.set('image', file)
    body.set('view_label', view)
    body.set('capture_id', capture)
    return request<Frame>(scenePath(id) + '/frames', { method: 'POST', body })
  },
  videos: (id: string, signal: AbortSignal) => request<VideoSummary[]>(videosPath(id), { signal }),
  video: (id: string, videoId: string, signal: AbortSignal) =>
    request<VideoPreview>(videoPath(id, videoId), { signal }),
  uploadVideo,
  importVideo: (id: string, videoId: string, candidates: string[], signal: AbortSignal) =>
    request<Frame[]>(videoPath(id, videoId) + '/import', { ...json({ candidate_ids: candidates }), signal }),
  revisions: (id: string, signal?: AbortSignal) =>
    request<Revision[]>(scenePath(id) + '/revisions', { signal }),
  freeze: (id: string, frameIds: string[]) =>
    request<Revision>(scenePath(id) + '/revisions', json({ frame_ids: frameIds })),
  jobs: (id: string, signal?: AbortSignal) => request<Job[]>(scenePath(id) + '/jobs', { signal }),
  enqueue: (revisionId: string, kind: Kind, recipeVersion = 'v1') =>
    request<Job>('/jobs', json({ revision_id: revisionId, kind, recipe_version: recipeVersion })),
  rerun: (jobId: string, key: string) =>
    request<TeamJob>('/jobs/' + encodeURIComponent(jobId) + '/rerun', {
      method: 'POST',
      headers: { 'Idempotency-Key': key },
    }),
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
