import { useEffect, useRef, useState } from 'react'
import { api, errorText, sources } from './api'
import type { Frame, Job, Kind, Revision, Scene } from './api'
import { SceneForm, UploadForm } from './Forms'
import { Gallery, JobsPanel, Viewport } from './Panels'

function Studio({ scene, revisionTick }: { scene: Scene; revisionTick: number }) {
  const [frames, setFrames] = useState<Frame[]>([])
  const [revisions, setRevisions] = useState<Revision[]>([])
  const [jobs, setJobs] = useState<Job[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [previewId, preview] = useState('')
  const [revisionId, choose] = useState('')
  const [tab, setTab] = useState<'capture' | 'jobs'>('capture')
  const [view, setView] = useState('正面')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [dataTick, reload] = useState(0)
  const seq = useRef(0)
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
        setJobs(js.sort((a, b) => b.created_at.localeCompare(a.created_at)))
        setSelected((old) => old.filter((key) => fs.some((f) => f.frame_id === key)))
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(errorText(err))
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [scene.scene_id, revisionTick, dataTick])
  function uploaded(accepted: Frame[]) {
    setNotice(`已上传 ${accepted.length} 张照片。`)
    preview(accepted[accepted.length - 1].frame_id)
    reload((v) => v + 1)
  }
  async function freeze() {
    if (busy || !selected.length) return
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
      setSelected([])
      setTab('jobs')
      setNotice(`已确认批次 v${item.version}，含 ${item.frame_ids.length} 张照片。`)
      reload((v) => v + 1)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }
  async function enqueue(id: string, kind: Kind) {
    if (busy) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const job = await api.enqueue(id, kind)
      setNotice(job.status === 'queued' ? '任务已入队，等待 GPU Worker。' : '已获取任务状态。')
      reload((v) => v + 1)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }
  const frame = frames.find((f) => f.frame_id === previewId)
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
          照片采集
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
          <button className="text-button" aria-label="关闭提示" onClick={() => setNotice('')}>
            关闭
          </button>
        </div>
      )}
      {tab === 'capture' ? (
        <div className="capture-grid">
          <Viewport frame={frame} view={view} reset={() => preview('')} />
          <UploadForm sceneId={scene.scene_id} view={view} setView={setView} onFrames={uploaded} />
          <Gallery
            frames={frames}
            selected={selected}
            previewId={previewId}
            preview={preview}
            busy={busy || loading}
            clear={() => setSelected([])}
            selectAll={() => setSelected(frames.map((f) => f.frame_id))}
            toggle={(id) =>
              setSelected((old) => (old.includes(id) ? old.filter((f) => f !== id) : [...old, id]))
            }
            freeze={() => void freeze()}
          />
        </div>
      ) : (
        <JobsPanel
          frames={frames}
          revisions={revisions}
          jobs={jobs}
          revisionId={revisionId}
          choose={choose}
          enqueue={enqueue}
          busy={busy || loading}
        />
      )}
    </>
  )
}

export function App() {
  const [scenes, setScenes] = useState<Scene[]>([])
  const [selected, setSelected] = useState('')
  const [creating, setCreating] = useState(false)
  const [tick, refresh] = useState(0)
  const [error, setError] = useState('')
  const [health, setHealth] = useState<'connecting' | 'online' | 'offline'>('connecting')
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError('')
    api
      .health(controller.signal)
      .then((body) => {
        if (!controller.signal.aborted) setHealth(body.status === 'ok' ? 'online' : 'offline')
      })
      .catch(() => {
        if (!controller.signal.aborted) setHealth('offline')
      })
    api
      .scenes(controller.signal)
      .then((items) => {
        if (controller.signal.aborted) return
        setScenes(items)
        setSelected((id) =>
          items.some((s) => s.scene_id === id) ? id : (items[0]?.scene_id ?? ''),
        )
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
    setScenes((old) => [scene, ...old.filter((s) => s.scene_id !== scene.scene_id)])
    setSelected(scene.scene_id)
    setCreating(false)
    setError('')
    refresh((t) => t + 1)
  }
  const scene = scenes.find((s) => s.scene_id === selected)
  const status = { connecting: '连接中', online: 'API 在线', offline: 'API 离线' }[health]
  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            <i />
          </span>
          <strong>绕物成景</strong>
        </div>
        <span className="brand-sub">空间视觉工作台</span>
        <div className="server-state" role="status">
          <i className={health} />
          {status}
        </div>
        <button className="refresh" onClick={() => refresh((t) => t + 1)} disabled={loading}>
          <span aria-hidden="true">↻</span> 刷新
        </button>
      </header>
      <aside className="sidebar">
        <div className="side-head">
          <h2>场景列表</h2>
          <span className="side-count">{scenes.length}</span>
        </div>
        <button className="new-scene" onClick={() => setCreating(true)}>
          <b aria-hidden="true">＋</b> 新建场景
        </button>
        <nav aria-label="场景列表">
          {scenes.map((s) => (
            <button
              className={'scene-link' + (s.scene_id === selected && !creating ? ' active' : '')}
              key={s.scene_id}
              onClick={() => {
                setSelected(s.scene_id)
                setCreating(false)
              }}
              aria-current={s.scene_id === selected && !creating ? 'true' : undefined}
            >
              <span className="cube-icon" aria-hidden="true">
                ◇
              </span>
              <span>
                <strong>{s.title}</strong>
                <small>{sources[s.source]}</small>
              </span>
            </button>
          ))}
        </nav>
        {!scenes.length && (
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
            <button className="text-button" onClick={() => refresh((t) => t + 1)}>
              重试
            </button>
          </div>
        )}
        {scene && !creating ? (
          <Studio key={scene.scene_id} scene={scene} revisionTick={tick} />
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
            <p className="intro">创建场景，按机位采集照片，并将确认的批次提交给三维重建任务。</p>
            <div className="capture-grid welcome">
              <Viewport view="正面" />
              <SceneForm created={created} cancel={scene ? () => setCreating(false) : undefined} />
            </div>
          </>
        )}
      </main>
    </div>
  )
}
