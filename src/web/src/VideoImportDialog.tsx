import { useEffect, useId, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { api, errorText } from './api'
import type { Frame, VideoPreview, VideoSummary } from './api'

function fileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KiB`
  return `${(bytes / 1024 ** 2).toFixed(1)} MiB`
}

export function VideoImportDialog({ sceneId, onImported, onClose }: {
  sceneId: string
  onImported: (frames: Frame[]) => void
  onClose: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const input = useRef<HTMLInputElement>(null)
  const request = useRef<AbortController>(undefined)
  const headingId = useId()
  const [file, setFile] = useState<File>()
  const [dragging, setDragging] = useState(false)
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

  function chooseFile(files: FileList | null) {
    if (operation || !files?.length) return
    const picked = files[0]
    if (files.length !== 1 || !picked.size || !picked.name.toLowerCase().endsWith('.mp4')) {
      setFile(undefined)
      setError('请选择一个 MP4 视频。')
    } else if (picked.size > 200 * 1024 * 1024) {
      setFile(undefined)
      setError('单个 MP4 视频最大为 200 MiB。')
    } else {
      setFile(picked)
      setError('')
    }
  }

  function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!file) return
    const data = new FormData(event.currentTarget)
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

  function toggleCandidate(id: string) {
    setSelected((previous) => {
      const next = new Set(previous)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const uploading = operation === 'upload'
  return (
    <dialog ref={dialog} className="card workbench-dialog video-import" aria-labelledby={headingId} onClose={onClose}>
      <div className="card-heading">
        <h2 id={headingId}>导入 MP4</h2>
        <button type="button" className="video-close text-button" aria-label="关闭"
          onClick={() => dialog.current?.close()}>×</button>
      </div>
      <div className="form-body">
        <form onSubmit={upload}>
          <fieldset disabled={!!operation} className="video-fields">
            <input ref={input} hidden type="file" name="video" accept="video/mp4,.mp4"
              aria-label="MP4 文件" onChange={(event) => {
                chooseFile(event.currentTarget.files)
                event.currentTarget.value = ''
              }} />
            <button type="button" className={'dropzone video-dropzone span-all' + (dragging ? ' dragging' : '')}
              title={file?.name}
              onClick={() => input.current?.click()}
              onDragOver={(event) => {
                event.preventDefault()
                if (event.dataTransfer.types.includes('Files')) {
                  event.dataTransfer.dropEffect = 'copy'
                  setDragging(true)
                }
              }}
              onDragLeave={(event) => {
                if (!(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget)) {
                  setDragging(false)
                }
              }}
              onDrop={(event) => {
                event.preventDefault()
                setDragging(false)
                chooseFile(event.dataTransfer.files)
              }}>
              <span className="video-drop-icon" aria-hidden="true">↑</span>
              <span className="video-drop-copy">
                <strong>{file ? file.name : '选择或拖入 MP4'}</strong>
                <small>{file ? fileSize(file.size) : 'MP4 · 单个视频最多 200 MiB'}</small>
              </span>
              <span className="video-drop-action">{file ? '重新选择' : '浏览文件'}</span>
            </button>
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
            <div className="video-upload-actions span-all">
              <button className="secondary video-upload-button" type="submit" disabled={!file}>
                {uploading ? (progress < 100 ? '正在上传…' : '正在抽帧…') : '上传并抽帧'}
              </button>
              {uploading && (
                <div className="video-upload-status" role="status">
                  <span>{progress === 100 ? '上传完成，正在抽帧…' : `已上传 ${progress}%`}</span>
                  <progress aria-label="MP4 上传进度" max={100} value={progress} />
                </div>
              )}
            </div>
          </fieldset>
        </form>
        {history.length > 0 && (
          <label className="video-history">已抽帧视频
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
          <section className="video-preview" aria-label="候选帧">
            <div className="video-preview-heading">
              <p>候选帧 <span className="hint">{video.candidates.length} 张</span></p>
              <div className="video-preview-actions">
                <button type="button" className="text-button" disabled={!!operation || selected.size === video.candidates.length}
                  onClick={() => setSelected(new Set(video.candidates.map((item) => item.candidate_id)))}>全选</button>
                <button type="button" className="text-button" disabled={!!operation || !selected.size}
                  onClick={() => setSelected(new Set())}>清空</button>
              </div>
            </div>
            <div className="video-candidates">
              {video.candidates.map((item) => (
                <div className="video-candidate" key={item.candidate_id}>
                  <button type="button" className="video-candidate-select" disabled={!!operation}
                    aria-pressed={selected.has(item.candidate_id)} onClick={() => toggleCandidate(item.candidate_id)}>
                    <span className="video-candidate-thumb">
                      <img src={item.image_url} alt="" loading="lazy" />
                      <span className="video-candidate-check" aria-hidden="true" />
                    </span>
                    <span className="video-candidate-caption">候选帧 {item.position}</span>
                  </button>
                  <a className="video-candidate-view" href={item.image_url} target="_blank" rel="noreferrer"
                    title="查看大图" aria-label={`查看候选帧 ${item.position} 大图`}>
                    <span aria-hidden="true">↗</span>
                  </a>
                </div>
              ))}
            </div>
          </section>
        )}
      </div>
      <footer className="dialog-actions video-footer">
        <button type="button" className="secondary" onClick={() => dialog.current?.close()}>取消</button>
        <button type="button" className="primary" disabled={!!operation || !selected.size} onClick={importSelected}>
          {operation === 'import' ? '正在导入…' : `导入选中帧 (${selected.size})`}
        </button>
      </footer>
    </dialog>
  )
}
