import { useEffect, useId, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { api, errorText } from './api'
import type { Frame, VideoPreview, VideoSummary } from './api'

export function VideoImportDialog({ sceneId, onImported, onClose }: {
  sceneId: string
  onImported: (frames: Frame[]) => void
  onClose: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const request = useRef<AbortController>(undefined)
  const headingId = useId()
  const [history, setHistory] = useState<VideoSummary[]>([])
  const [historyError, setHistoryError] = useState('')
  const [video, setVideo] = useState<VideoPreview>()
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [progress, setProgress] = useState(0)
  const [operation, setOperation] = useState<'upload' | 'preview' | 'import'>()
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    const element = dialog.current
    if (element && !element.open) element.showModal()
    api.videos(sceneId, controller.signal).then((items) => {
      if (!controller.signal.aborted) {
        setHistory((current) => [...new Map([...items, ...current].map((item) => [item.video_id, item])).values()])
      }
    }).catch((err) => {
      if (!controller.signal.aborted) setHistoryError(errorText(err))
    })
    return () => {
      controller.abort()
      request.current?.abort()
    }
  }, [sceneId])

  async function run(task: NonNullable<typeof operation>, action: (signal: AbortSignal) => Promise<void>) {
    if (request.current) return
    const controller = new AbortController()
    request.current = controller
    setError('')
    setOperation(task)
    try {
      await action(controller.signal)
    } catch (err) {
      if (!controller.signal.aborted) setError(errorText(err))
    } finally {
      request.current = undefined
      if (!controller.signal.aborted) setOperation(undefined)
    }
  }

  function showPreview(next: VideoPreview) {
    setVideo(next)
    setSelected(new Set())
  }

  function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    const file = data.get('video')
    if (!(file instanceof File) || !file.size || !file.name.toLowerCase().endsWith('.mp4')) {
      setError('请选择一个 MP4 视频。')
      return
    }
    if (file.size > 200 * 1024 * 1024) {
      setError('单个 MP4 视频最大为 200 MiB。')
      return
    }
    const duration = data.get('duration')
    setProgress(0)
    void run('upload', async (signal) => {
      const result = await api.uploadVideo(sceneId, file, {
        start_seconds: Number(data.get('start')),
        duration_seconds: duration === '' ? null : Number(duration),
        fps: Number(data.get('fps')),
        max_frames: Number(data.get('maxFrames')),
      }, setProgress, signal)
      if (!signal.aborted) {
        setHistory((items) => [result, ...items])
        showPreview(result)
      }
    })
  }

  function importSelected() {
    if (!video || !selected.size) return
    const ids = video.candidates.filter((item) => selected.has(item.candidate_id)).map((item) => item.candidate_id)
    void run('import', async (signal) => {
      const frames = await api.importVideo(sceneId, video.video_id, ids, signal)
      if (!signal.aborted) {
        onImported(frames)
        dialog.current?.close()
      }
    })
  }

  return (
    <dialog ref={dialog} className="card workbench-dialog video-import" aria-labelledby={headingId} onClose={onClose}>
      <div className="card-heading">
        <h2 id={headingId}>导入 MP4</h2>
        <button className="text-button" onClick={() => dialog.current?.close()}>关闭</button>
      </div>
      <div className="form-body">
        <form onSubmit={upload}>
          <fieldset disabled={!!operation} className="video-fields">
            <label className="span-all">MP4 文件（最多 200 MiB）
              <input type="file" name="video" accept="video/mp4,.mp4" required />
            </label>
            <label>开始时间（秒）
              <input type="number" name="start" min="0" max="86400" step="any" defaultValue="0" required />
            </label>
            <label>抽帧时长（秒）
              <input type="number" name="duration" min="0.001" max="600" step="any" placeholder="留空则取剩余区间" />
            </label>
            <label>帧率（fps）
              <input type="number" name="fps" min="0.1" max="30" step="any" defaultValue="2" required />
            </label>
            <label>帧数上限
              <input type="number" name="maxFrames" min="1" max="120" defaultValue="120" required />
            </label>
            <button className="secondary span-all" type="submit">上传并抽帧</button>
          </fieldset>
        </form>
        {operation === 'upload' && (
          <div role="status">
            <progress aria-label="MP4 上传进度" max={100} value={progress} />
            <span>{progress === 100 ? '上传完成，正在抽帧…' : `已上传 ${progress}%`}</span>
          </div>
        )}
        {history.length > 0 && (
          <label>已抽帧视频
            <select value={video?.video_id ?? ''} disabled={!!operation} onChange={(event) => {
              const id = event.currentTarget.value
              void run('preview', async (signal) => {
                const result = await api.video(sceneId, id, signal)
                if (!signal.aborted) showPreview(result)
              })
            }}>
              <option value="" disabled>选择视频查看候选帧</option>
              {history.map((item) => <option key={item.video_id} value={item.video_id}>{item.filename}</option>)}
            </select>
          </label>
        )}
        {historyError && <p className="hint" role="status">读取已抽帧视频失败。{historyError}</p>}
        {operation === 'preview' && <p role="status">正在读取候选帧…</p>}
        {error && <p className="error" role="alert">{error}</p>}
        {video && (
          <section aria-label="候选帧">
            <p className="hint">已抽出 {video.candidates.length} 帧。勾选清晰的画面后导入。</p>
            <div className="video-candidates">
              {video.candidates.map((item) => (
                <div className="video-candidate" key={item.candidate_id}>
                  <a href={item.image_url} target="_blank" rel="noreferrer" aria-label={`查看候选帧 ${item.position} 大图`}>
                    <img src={item.image_url} alt={`候选帧 ${item.position}`} loading="lazy" />
                  </a>
                  <label>
                    <input type="checkbox" disabled={!!operation} checked={selected.has(item.candidate_id)}
                      onChange={(event) => {
                        const checked = event.currentTarget.checked
                        setSelected((previous) => {
                          const next = new Set(previous)
                          if (checked) next.add(item.candidate_id)
                          else next.delete(item.candidate_id)
                          return next
                        })
                      }} />
                    候选帧 {item.position}
                  </label>
                </div>
              ))}
            </div>
            <button className="primary" disabled={!!operation || !selected.size} onClick={importSelected}>
              {operation === 'import' ? '正在导入…' : `导入选中帧（${selected.size}）`}
            </button>
          </section>
        )}
      </div>
    </dialog>
  )
}
