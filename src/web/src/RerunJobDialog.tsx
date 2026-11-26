import { useEffect, useId, useRef, useState } from 'react'
import { api, ApiError, errorText, kinds, recipeLabel } from './api'
import type { Job, Revision, TeamJob } from './api'

const blockedCodes = new Set(['SCENE_ARCHIVED', 'JOB_NOT_FOUND', 'REVISION_NOT_FOUND',
  'UNKNOWN_RECIPE', 'FRAME_COUNT_MISMATCH', 'RERUN_KEY_CONFLICT'])

export function RerunJobDialog({ job, batch, onSubmitted, onClose }: {
  job: Job
  batch: Revision
  onSubmitted: (run: TeamJob) => void
  onClose: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const key = useRef<string | null>(null)
  const titleId = useId()
  const summaryId = useId()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [blocked, setBlocked] = useState(false)
  const recipe = recipeLabel(job)

  useEffect(() => {
    const element = dialog.current
    if (element && !element.open) element.showModal()
  }, [])

  async function confirm() {
    if (busy || blocked) return
    setBusy(true)
    setError('')
    try {
      const run = await api.rerun(job.job_id, key.current ??= crypto.randomUUID())
      onSubmitted(run)
      dialog.current?.close()
    } catch (err) {
      setError(errorText(err))
      if (err instanceof ApiError && err.code && blockedCodes.has(err.code)) setBlocked(true)
    } finally {
      setBusy(false)
    }
  }

  return (
    <dialog className="card workbench-dialog rerun-job" ref={dialog}
      aria-labelledby={titleId} aria-describedby={summaryId} onClose={onClose}
      onCancel={(event) => { if (busy) event.preventDefault() }}>
      <div className="card-heading">
        <h2 id={titleId}>重跑任务</h2>
      </div>
      <div className="form-body">
        <dl className="rerun-details">
          <dt>原批次</dt><dd>v{batch.version} · {batch.frame_ids.length} 张照片</dd>
          <dt>任务类型</dt><dd>{kinds[job.kind]}</dd>
          <dt>原配方</dt><dd>{recipe === job.recipe_version ? recipe : `${recipe}（${job.recipe_version}）`}</dd>
        </dl>
        <p className="hint" id={summaryId}>新任务会进入队列。已有成功模型可继续查看，新运行成功后查看器才会切换。</p>
        {error && <p className="error" role="alert">{error}</p>}
        <div className="dialog-actions">
          <button className="secondary" autoFocus disabled={busy} onClick={() => dialog.current?.close()}>取消</button>
          <button className="primary" disabled={busy || blocked} onClick={() => void confirm()}>
            {busy ? '正在提交…' : error && !blocked ? '重试提交' : '确认重跑'}
          </button>
        </div>
      </div>
    </dialog>
  )
}
