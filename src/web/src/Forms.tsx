import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { api, errorText, sources, views } from './api'
import type { Frame, Scene, Source } from './api'

export function SceneForm({
  created,
  cancel,
}: {
  created: (scene: Scene) => void
  cancel?: () => void
}) {
  const [title, setTitle] = useState('')
  const [target, setTarget] = useState('')
  const [source, setSource] = useState<Source>('sample')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])
  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!title.trim() || busy) return
    setBusy(true)
    setError('')
    try {
      const scene = await api.create(title.trim(), target.trim(), source)
      if (mounted.current) created(scene)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }
  return (
    <section className="card form-card">
      <div className="card-heading">
        <h2>新建场景</h2>
        {cancel && (
          <button className="text-button" onClick={cancel}>
            取消
          </button>
        )}
      </div>
      <form onSubmit={submit} className="form-body">
        <label>
          场景名称
          <input
            required
            maxLength={120}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="例如，桌面玩具扫描"
          />
        </label>
        <label>
          采集目标 <span className="optional">选填</span>
          <input
            maxLength={120}
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            placeholder="例如，带背面贴纸的小熊"
          />
        </label>
        <label>
          照片来源
          <select value={source} onChange={(e) => setSource(e.target.value as Source)}>
            {Object.entries(sources).map(([key, name]) => (
              <option key={key} value={key}>
                {name}
              </option>
            ))}
          </select>
        </label>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button className="primary" disabled={busy || !title.trim()}>
          {busy ? '正在创建…' : '创建场景'}
        </button>
      </form>
    </section>
  )
}

interface Pending {
  file: File
  id: string
}
export function UploadForm({
  sceneId,
  view,
  setView,
  onFrames,
}: {
  sceneId: string
  view: string
  setView: (value: string) => void
  onFrames: (frames: Frame[]) => void
}) {
  const [files, setFiles] = useState<Pending[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [dragging, setDragging] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const active = useRef(true)
  useEffect(() => {
    active.current = true
    return () => {
      active.current = false
    }
  }, [])
  function add(list: FileList | null) {
    if (!list || busy) return
    const supported = new Set(['image/jpeg', 'image/png', 'image/webp'])
    const pending: Pending[] = []
    const invalid = []
    for (const file of Array.from(list)) {
      const isImage = file.type ? supported.has(file.type) : /\.(jpe?g|png|webp)$/i.test(file.name)
      if (file.size > 12 * 1024 * 1024 || !isImage) invalid.push(file.name)
      else {
        const bytes = crypto.getRandomValues(new Uint8Array(16))
        const id = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
        pending.push({ file, id })
      }
    }
    setError(invalid.length ? `格式或大小不符合要求：${invalid.join('、')}` : '')
    setFiles((previous) => [...previous, ...pending])
  }
  async function submit(e: FormEvent) {
    e.preventDefault()
    if (busy || !files.length) return
    setBusy(true)
    setError('')
    const accepted: Frame[] = []
    try {
      for (const item of files) {
        if (!active.current) break
        accepted.push(await api.upload(sceneId, item.file, view, item.id))
        setFiles((current) => current.filter((file) => file.id !== item.id))
      }
    } catch (err) {
      setError(errorText(err))
    } finally {
      if (active.current) {
        if (accepted.length) onFrames(accepted)
        setBusy(false)
      }
    }
  }
  return (
    <section className="card form-card">
      <div className="card-heading">
        <h2>添加照片</h2>
      </div>
      <form className="form-body" onSubmit={submit}>
        <label>
          拍摄机位
          <select value={view} disabled={busy} onChange={(e) => setView(e.target.value)}>
            {views.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        <input
          className="visually-hidden"
          ref={input}
          type="file"
          multiple
          accept="image/jpeg,image/png,image/webp"
          tabIndex={-1}
          aria-label="照片文件"
          onChange={(e) => {
            add(e.target.files)
            e.target.value = ''
          }}
        />
        <button
          type="button"
          className={'dropzone' + (dragging ? ' dragging' : '')}
          disabled={busy}
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            add(e.dataTransfer.files)
          }}
          onClick={() => input.current?.click()}
        >
          <span className="upload-icon" aria-hidden="true">
            ↑
          </span>
          <strong>选择或拖入照片</strong>
          <small>JPG / PNG / WebP · 单张 ≤ 12 MiB</small>
        </button>
        {files.length > 0 && (
          <ul className="pending-files">
            {files.map((item) => (
              <li key={item.id}>
                <span title={item.file.name}>{item.file.name}</span>
                <button
                  className="text-button"
                  type="button"
                  disabled={busy}
                  aria-label={'移除 ' + item.file.name}
                  onClick={() => setFiles((items) => items.filter((f) => f.id !== item.id))}
                >
                  移除
                </button>
              </li>
            ))}
          </ul>
        )}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button className="primary" disabled={busy || !files.length}>
          {busy ? '正在上传…' : files.length ? `上传 ${files.length} 张照片` : '上传照片'}
        </button>
      </form>
    </section>
  )
}
