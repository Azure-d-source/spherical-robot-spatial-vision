import { useEffect, useId, useRef, useState } from 'react'
import { api, errorText } from './api'
import type { Frame, UploadRecord } from './api'
import { frameLabel } from './simulationLayout'

const uploadTime = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'medium' })

type History =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; records: UploadRecord[] }

export function UploadHistoryDialog({ sceneId, frame, onClose }: {
  sceneId: string
  frame: Frame
  onClose: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  const [history, setHistory] = useState<History>({ status: 'loading' })
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    const element = dialog.current
    if (element && !element.open) element.showModal()
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    const { signal } = controller
    api.uploadHistory(sceneId, frame.frame_id, signal)
      .then((records) => {
        if (!signal.aborted) setHistory({ status: 'ready', records })
      })
      .catch((error) => {
        if (!signal.aborted) setHistory({ status: 'error', message: errorText(error) })
      })
    return () => controller.abort()
  }, [sceneId, frame.frame_id, retry])

  return (
    <dialog className="card upload-history" ref={dialog} aria-labelledby={titleId} onClose={onClose}>
      <div className="card-heading">
        <h2 id={titleId}>上传记录</h2>
        <button className="text-button" onClick={() => dialog.current?.close()}>关闭</button>
      </div>
      <div className="form-body">
        <p className="hint">{frame.filename}</p>
        {history.status === 'loading' && <p role="status">正在读取上传记录…</p>}
        {history.status === 'error' && (
          <>
            <p className="error" role="alert">{history.message}</p>
            <button className="secondary" onClick={() => {
              setHistory({ status: 'loading' })
              setRetry((value) => value + 1)
            }}>重新读取</button>
          </>
        )}
        {history.status === 'ready' && (history.records.length ? (
          <ul className="upload-history-list">
            {history.records.map((record) => (
              <li key={record.upload_id}>
                <strong>{record.uploader_email}</strong>
                <span>{frameLabel(record.view_label)}</span>
                <time dateTime={record.created_at}>{uploadTime.format(new Date(record.created_at))}</time>
              </li>
            ))}
          </ul>
        ) : <p className="hint">暂无上传记录</p>)}
      </div>
    </dialog>
  )
}
