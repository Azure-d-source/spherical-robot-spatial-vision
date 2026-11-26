import { useEffect, useId, useRef, useState } from 'react'
import { ApiError, errorText } from './api'
import type { Frame } from './api'

const blockedCodes = new Set(['FRAME_IN_USE', 'SCENE_ARCHIVED', 'FRAME_WITHDRAW_FORBIDDEN', 'FRAME_NOT_FOUND'])

export function WithdrawPhotoDialog({ frame, onConfirm, onClose }: {
  frame: Frame
  onConfirm: (frame: Frame) => Promise<void>
  onClose: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  const descriptionId = useId()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [blocked, setBlocked] = useState(false)

  useEffect(() => {
    const element = dialog.current
    if (element && !element.open) element.showModal()
  }, [])

  async function confirm() {
    if (busy || blocked) return
    setBusy(true)
    setError('')
    try {
      await onConfirm(frame)
      dialog.current?.close()
    } catch (err) {
      setError(errorText(err))
      if (err instanceof ApiError && err.code && blockedCodes.has(err.code)) setBlocked(true)
    } finally {
      setBusy(false)
    }
  }

  return (
    <dialog className="card workbench-dialog withdraw-photo" ref={dialog}
      aria-labelledby={titleId} aria-describedby={descriptionId} onClose={onClose}
      onCancel={(event) => { if (busy) event.preventDefault() }}>
      <div className="card-heading">
        <h2 id={titleId}>撤下照片</h2>
      </div>
      <div className="form-body">
        <div id={descriptionId} className="withdraw-description">
          <strong>{frame.filename}</strong>
          <p className="hint">撤下后，这张照片会从场景照片列表和待确认批次中移出。系统会保留原文件和上传记录。</p>
          <p className="hint">已用于批次的照片禁止撤下。</p>
        </div>
        {error && <p className="error" role="alert">{error}</p>}
        <div className="dialog-actions">
          <button className="secondary" autoFocus disabled={busy} onClick={() => dialog.current?.close()}>取消</button>
          <button className="secondary danger-action" disabled={busy || blocked} onClick={() => void confirm()}>
            {busy ? '正在撤下…' : '确认撤下'}
          </button>
        </div>
      </div>
    </dialog>
  )
}
