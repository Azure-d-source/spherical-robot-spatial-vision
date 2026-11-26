import { useEffect, useRef, useState } from 'react'
import { api, errorText, sources } from './api'
import type { Account, Frame, Job, Kind, Revision, Scene, SceneStatus } from './api'
import { SceneForm, UploadForm } from './Forms'
import { Gallery, JobsPanel, Viewport } from './Panels'
import { ViewerStage } from './components/viewers/ViewerStage'
import type { ViewerMode } from './components/viewers/ViewerStage'
import { frameLayout, initialLayout, layoutKey } from './simulationLayout'
import type { SimulationLayout } from './simulationLayout'
import { SceneManagement } from './SceneManagement'
import { SessionGate, WorkbenchBrand } from './SessionGate'
import { UploadHistoryDialog } from './UploadHistoryDialog'

const sceneFilters: { status: 'all' | SceneStatus; label: string }[] = [
  { status: 'all', label: '全部' },
  { status: 'active', label: '进行中' },
  { status: 'archived', label: '已归档' },
]

function newestJobs(jobs: Job[]) {
  return [...jobs].sort(
    (a, b) =>
      b.created_at.localeCompare(a.created_at) ||
      b.job_id.localeCompare(a.job_id),
  )
}

function Studio({
  scene,
  revisionTick,
  canManage,
  onSceneChange,
  showUploadHistory,
}: {
  scene: Scene
  revisionTick: number
  canManage: boolean
  onSceneChange: (scene: Scene) => void
  showUploadHistory: boolean
}) {
  const [frames, setFrames] = useState<Frame[]>([])
  const [historyFrame, setHistoryFrame] = useState<Frame>()
  const [revisions, setRevisions] = useState<Revision[]>([])
  const [jobs, setJobs] = useState<Job[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [layout, setLayout] = useState(initialLayout)
  const [galleryLayout, setGalleryLayout] = useState('')
  const galleryLayoutRef = useRef('')
  const [previewId, preview] = useState('')
  const [revisionId, choose] = useState('')
  const [viewerMode, setViewerMode] = useState<ViewerMode>('camera')
  const [tab, setTab] = useState<'capture' | 'jobs'>('capture')
  const [view, setView] = useState('正面')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [dataTick, reload] = useState(0)
  const seq = useRef(0)
  const archived = scene.status === 'archived'
  const hasActiveJobs = jobs.some(
    (job) => job.status === 'queued' || job.status === 'running',
  )
  useEffect(() => {
    const controller = new AbortController()
    const version = ++seq.current
    setLoading(true)
    setError('')
    const id = scene.scene_id
    Promise.all([
      api.frames(id, controller.signal),
      api.revisions(id, controller.signal),
      api.jobs(id, controller.signal),
    ])
      .then(([fs, rs, js]) => {
        if (version !== seq.current || controller.signal.aborted) return
        setFrames(fs)
        setRevisions(rs.sort((a, b) => b.version - a.version))
        setJobs(newestJobs(js))
        setSelected((old) =>
          old.filter((key) => fs.some((f) => f.frame_id === key)),
        )
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(errorText(err))
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [scene.scene_id, revisionTick, dataTick])

  useEffect(() => {
    if (!hasActiveJobs || loading) return
    let timer: ReturnType<typeof setTimeout> | undefined
    let request: AbortController | undefined
    let active = true

    function pause() {
      clearTimeout(timer)
      request?.abort()
      request = undefined
    }

    async function poll() {
      const controller = new AbortController()
      request = controller
      try {
        const next = await api.jobs(scene.scene_id, controller.signal)
        if (!controller.signal.aborted) setJobs(newestJobs(next))
      } catch {
        // Retry transient errors without discarding the last known results.
      } finally {
        if (active && request === controller && !document.hidden) {
          timer = setTimeout(() => void poll(), 1500)
        }
      }
    }

    function visibilityChanged() {
      pause()
      if (!document.hidden) void poll()
    }

    document.addEventListener('visibilitychange', visibilityChanged)
    if (!document.hidden) timer = setTimeout(() => void poll(), 1500)
    return () => {
      active = false
      pause()
      document.removeEventListener('visibilitychange', visibilityChanged)
    }
  }, [scene.scene_id, hasActiveJobs, loading])
  function uploaded(accepted: Frame[]) {
    setNotice(`已上传 ${accepted.length} 张照片。`)
    preview(accepted[accepted.length - 1].frame_id)
    reload((v) => v + 1)
  }
  function showLayout(key: string) {
    if (galleryLayoutRef.current === key) return
    galleryLayoutRef.current = key
    setGalleryLayout(key)
    setSelected([])
  }
  function moveExhibit(next: SimulationLayout) {
    setLayout(next)
    showLayout(layoutKey(next))
  }
  function virtualCaptured(accepted: Frame[]) {
    const key = frameLayout(accepted[0].view_label) ?? ''
    if (galleryLayoutRef.current === key) {
      setSelected((old) => [...new Set([...old, ...accepted.map((f) => f.frame_id)])])
      preview(accepted.at(-1)!.frame_id)
    }
    setFrames((old) => [...new Map([...old, ...accepted].map((f) => [f.frame_id, f])).values()])
    setNotice(`本次仿真采集上传 ${accepted.length} 张照片。`)
    reload((v) => v + 1)
  }
  function showFrame(id: string) {
    preview(id)
    setViewerMode('camera')
  }
  function selectRevision(id: string) {
    choose(id)
    preview(revisions.find((item) => item.revision_id === id)?.frame_ids[0] ?? '')
  }
  async function freeze() {
    if (archived || busy || !selected.length) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const item = await api.freeze(scene.scene_id, selected)
      setRevisions((items) =>
        [item, ...items.filter((r) => r.revision_id !== item.revision_id)].sort(
          (a, b) => b.version - a.version,
        ),
      )
      choose(item.revision_id)
      preview(item.frame_ids[0])
      setSelected([])
      setTab('jobs')
      setNotice(
        `已确认批次 v${item.version}，含 ${item.frame_ids.length} 张照片。`,
      )
      reload((v) => v + 1)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }
  async function enqueue(id: string, kind: Kind, recipeVersion: string) {
    if (archived || busy) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const job = await api.enqueue(id, kind, recipeVersion)
      setNotice(
        job.status === 'queued'
          ? '任务已入队，等待 GPU Worker。'
          : '已获取任务状态。',
      )
      reload((v) => v + 1)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }
  const activeRevision =
    revisions.find((revision) => revision.revision_id === revisionId) ??
    revisions[0]
  const visibleFrameId = tab === 'jobs' && activeRevision && !activeRevision.frame_ids.includes(previewId)
    ? activeRevision.frame_ids[0]
    : previewId
  const frame = frames.find((f) => f.frame_id === visibleFrameId)
  const frameLayouts = new Map(frames.map((f) => [f.frame_id, frameLayout(f.view_label) ?? '']))
  const layoutChoices = [...new Set(['', ...frameLayouts.values(), galleryLayout])]
  const galleryFrames = frames.filter((f) => frameLayouts.get(f.frame_id) === galleryLayout)
  const revisionLayouts = new Map<string, string>()
  for (const revision of revisions) {
    const key = frameLayouts.get(revision.frame_ids[0])
    if (key) revisionLayouts.set(revision.revision_id, key)
  }
  return (
    <>
      <div className="workspace-heading">
        <div>
          <div className="context-line">
            <span className="dash" />
            采集工作台
          </div>
          <h1>{scene.title}</h1>
        </div>
        <div className="source-pill">{sources[scene.source]}</div>
      </div>
      {canManage && <SceneManagement scene={scene} onChange={onSceneChange} />}
      {archived && <p className="notice archive-notice" role="status">场景已归档，仅可查看照片、批次和重建结果。</p>}
      {scene.target && (
        <p className="target-line">
          采集目标 <strong>{scene.target}</strong>
        </p>
      )}
      <div className="tabbar">
        <button
          className={tab === 'capture' ? 'active' : ''}
          aria-pressed={tab === 'capture'}
          onClick={() => setTab('capture')}
        >
          {archived ? '照片回看' : '照片采集'}
        </button>
        <button
          className={tab === 'jobs' ? 'active' : ''}
          aria-pressed={tab === 'jobs'}
          onClick={() => setTab('jobs')}
        >
          批次与任务
        </button>
        {loading && (
          <span className="loading" role="status">
            同步中…
          </span>
        )}
      </div>
      {error && (
        <div className="notice error" role="alert">
          {error}
          <button className="text-button" onClick={() => reload((v) => v + 1)}>
            重新读取
          </button>
        </div>
      )}
      {notice && (
        <div className="notice" role="status">
          {notice}
          <button
            className="text-button"
            aria-label="关闭提示"
            onClick={() => setNotice('')}
          >
            关闭
          </button>
        </div>
      )}
      <div className="capture-grid">
        <ViewerStage
          className={tab === 'jobs' || archived ? 'span-all' : undefined}
          sceneId={scene.scene_id}
          revision={activeRevision}
          revisions={revisions}
          revisionLayouts={revisionLayouts}
          jobs={jobs}
          frame={frame}
          view={view}
          mode={archived && viewerMode === 'virtual' ? 'camera' : viewerMode}
          readOnly={archived}
          onMode={(mode) => {
            if (mode === 'virtual') showLayout(layoutKey(layout))
            setViewerMode(mode)
          }}
          onRevision={selectRevision}
          layout={layout}
          onLayout={moveExhibit}
          onCaptured={virtualCaptured}
          resetFrame={() => preview('')}
        />
        {tab === 'capture' ? (
          <>
            {!archived && <UploadForm
              sceneId={scene.scene_id}
              view={view}
              setView={setView}
              onFrames={(accepted) => {
                showLayout('')
                uploaded(accepted)
              }}
            />}
            <Gallery
              frames={galleryFrames}
              layouts={layoutChoices}
              layout={galleryLayout}
              showLayout={showLayout}
              selected={selected}
              previewId={previewId}
              preview={showFrame}
              busy={busy || loading}
              readOnly={archived}
              showUploads={showUploadHistory ? setHistoryFrame : undefined}
              clear={() => setSelected([])}
              selectAll={() => setSelected(galleryFrames.map((f) => f.frame_id))}
              toggle={(id) =>
                setSelected((old) =>
                  old.includes(id) ? old.filter((f) => f !== id) : [...old, id],
                )
              }
              freeze={() => void freeze()}
            />
          </>
        ) : (
          <div className="span-all">
            <JobsPanel
              frames={frames}
              revisions={revisions}
              revisionLayouts={revisionLayouts}
              jobs={jobs}
              revisionId={activeRevision?.revision_id ?? ''}
              choose={selectRevision}
              preview={showFrame}
              enqueue={enqueue}
              busy={busy || loading}
              readOnly={archived}
            />
          </div>
        )}
      </div>
      {historyFrame && (
        <UploadHistoryDialog sceneId={scene.scene_id} frame={historyFrame} onClose={() => setHistoryFrame(undefined)} />
      )}
    </>
  )
}

function Workbench({ account, onLogout }: {
  account?: Account
  onLogout?: () => Promise<void>
}) {
  const [scenes, setScenes] = useState<Scene[]>([])
  const [selected, setSelected] = useState('')
  const [creating, setCreating] = useState(false)
  const [filter, setFilter] = useState<'all' | SceneStatus>('all')
  const [tick, refresh] = useState(0)
  const [error, setError] = useState('')
  const [health, setHealth] = useState<'connecting' | 'online' | 'offline'>(
    'connecting',
  )
  const [loading, setLoading] = useState(true)
  const [loggingOut, setLoggingOut] = useState(false)
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError('')
    api
      .health(controller.signal)
      .then((body) => {
        if (!controller.signal.aborted)
          setHealth(body.status === 'ok' ? 'online' : 'offline')
      })
      .catch(() => {
        if (!controller.signal.aborted) setHealth('offline')
      })
    api
      .scenes(controller.signal)
      .then((items) => {
        if (controller.signal.aborted) return
        setScenes(items)
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(errorText(err))
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [tick])
  function created(scene: Scene) {
    setScenes((old) => [
      scene,
      ...old.filter((s) => s.scene_id !== scene.scene_id),
    ])
    setSelected(scene.scene_id)
    setFilter('all')
    setCreating(false)
    setError('')
    refresh((t) => t + 1)
  }
  function updateScene(scene: Scene) {
    setScenes((old) => old.map((item) => item.scene_id === scene.scene_id ? scene : item))
    refresh((value) => value + 1)
  }

  async function logout() {
    if (!onLogout || loggingOut) return
    setLoggingOut(true)
    setError('')
    try {
      await onLogout()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setLoggingOut(false)
    }
  }

  const visibleScenes = filter === 'all' ? scenes : scenes.filter((item) => item.status === filter)
  const scene = visibleScenes.find((item) => item.scene_id === selected) ?? visibleScenes[0]
  const status = {
    connecting: '连接中',
    online: 'API 在线',
    offline: 'API 离线',
  }[health]
  return (
    <div className="shell">
      <header className="topbar">
        <WorkbenchBrand />
        <div className="server-state" role="status">
          <i className={health} />
          {status}
        </div>
        <button
          className="refresh"
          onClick={() => refresh((t) => t + 1)}
          disabled={loading}
        >
          <span aria-hidden="true">↻</span> 刷新
        </button>
        {account && (
          <>
            <span className="account-label" title={account.email}>{account.email}</span>
            <button className="secondary logout" disabled={loggingOut} onClick={() => void logout()}>
              {loggingOut ? '正在退出…' : '退出登录'}
            </button>
          </>
        )}
      </header>
      <aside className="sidebar">
        <div className="side-head">
          <h2>场景列表</h2>
          <span className="side-count">{visibleScenes.length}</span>
        </div>
        <button className="new-scene" onClick={() => setCreating(true)}>
          <b aria-hidden="true">＋</b> 新建场景
        </button>
        {account && (
          <div className="scene-filters" role="group" aria-label="筛选场景状态">
            {sceneFilters.map(({ status, label }) => (
              <button key={status} aria-pressed={filter === status}
                onClick={() => {
                  setFilter(status)
                  setCreating(false)
                }}>{label}</button>
            ))}
          </div>
        )}
        <nav aria-label="场景列表">
          {visibleScenes.map((s) => (
            <button
              className={
                'scene-link' +
                (s.scene_id === scene?.scene_id && !creating ? ' active' : '')
              }
              key={s.scene_id}
              onClick={() => {
                setSelected(s.scene_id)
                setCreating(false)
              }}
              aria-current={
                s.scene_id === scene?.scene_id && !creating ? 'true' : undefined
              }
            >
              <span className="cube-icon" aria-hidden="true">
                ◇
              </span>
              <span>
                <strong>{s.title}</strong>
                <small>{s.status === 'archived' ? '已归档' : sources[s.source]}</small>
              </span>
            </button>
          ))}
        </nav>
        {!visibleScenes.length && (
          <p className="side-empty">
            {loading ? '正在读取场景…' : error ? '场景读取失败' : '尚无场景'}
          </p>
        )}
        <div className="side-footer">
          <a href="/docs" target="_blank" rel="noreferrer">
            API 文档 <span aria-hidden="true">↗</span>
          </a>
        </div>
      </aside>
      <main>
        {error && (
          <div className="notice error" role="alert">
            {error}
            <button
              className="text-button"
              onClick={() => refresh((t) => t + 1)}
            >
              重试
            </button>
          </div>
        )}
        {scene && !creating ? (
          <Studio key={scene.scene_id} scene={scene} revisionTick={tick}
            canManage={!!account && (account.role === 'admin' || account.account_id === scene.owner_id)}
            onSceneChange={updateScene} showUploadHistory={!!account} />
        ) : filter === 'archived' && !creating ? (
          <p className="empty">{loading ? '正在读取已归档场景…' : '暂无已归档场景'}</p>
        ) : (
          <>
            <div className="workspace-heading">
              <div>
                <div className="context-line">
                  <span className="dash" />
                  空间采集
                </div>
                <h1>采集工作台</h1>
              </div>
            </div>
            <p className="intro">
              创建场景，按机位采集照片，并将确认的批次提交给三维重建任务。
            </p>
            <div className="capture-grid welcome">
              <Viewport view="正面" />
              <SceneForm
                created={created}
                cancel={creating ? () => setCreating(false) : undefined}
              />
            </div>
          </>
        )}
      </main>
    </div>
  )
}

export function App() {
  return (
    <SessionGate>
      {(account, logout) => <Workbench account={account} onLogout={logout} />}
    </SessionGate>
  )
}
