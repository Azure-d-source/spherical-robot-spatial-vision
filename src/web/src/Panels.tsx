import { useState } from 'react'
import { kinds, timeLabel } from './api'
import type { Frame, Job, Kind, Revision } from './api'
import { OrbitView } from './OrbitView'
import { frameLabel, layoutTitle } from './simulationLayout'

export function Viewport({
  frame,
  view,
  reset,
}: {
  frame?: Frame
  view: string
  reset?: () => void
}) {
  return (
    <section className="card viewport">
      <div className="card-heading">
        <h2>采集视图</h2>
        {frame ? (
          <button className="text-button" onClick={reset}>
            查看机位示意
          </button>
        ) : (
          <span className="metadata">机位示意</span>
        )}
      </div>
      <div className="view-content">
        <i className="corner tl" aria-hidden="true" />
        <i className="corner tr" aria-hidden="true" />
        <i className="corner bl" aria-hidden="true" />
        <i className="corner br" aria-hidden="true" />
        {frame ? (
          <img
            className="full-frame"
            src={frame.image_url}
            alt={frame.view_label + '机位原图：' + frame.filename}
          />
        ) : (
          <OrbitView view={view} />
        )}
      </div>
      <div className="viewport-footer">
        <span className="micro-tag">{frame ? 'RGB' : 'REF'}</span>
        <span className="ellipsize" title={frame?.filename}>
          {frame?.filename ?? '拍摄方位参考'}
        </span>
        <span className="meta-right">{frame ? frameLabel(frame.view_label) : view}</span>
      </div>
    </section>
  )
}

export function Gallery({
  frames,
  layouts,
  layout,
  showLayout,
  selected,
  toggle,
  preview,
  previewId,
  freeze,
  busy,
  readOnly,
  showUploads,
  clear,
  selectAll,
}: {
  frames: Frame[]
  layouts: string[]
  layout: string
  showLayout: (key: string) => void
  selected: string[]
  toggle: (id: string) => void
  preview: (id: string) => void
  previewId?: string
  freeze: () => void
  busy: boolean
  readOnly: boolean
  showUploads?: (frame: Frame) => void
  clear: () => void
  selectAll: () => void
}) {
  return (
    <section className={'card gallery' + (readOnly ? ' span-all' : '')}>
      <div className="card-heading">
        <h2>
          采集照片 <span className="counter">{frames.length}</span>
        </h2>
        {frames.length > 0 && !readOnly && (
          <button
            className="text-button"
            disabled={busy}
            onClick={selected.length === frames.length ? clear : selectAll}
          >
            {selected.length === frames.length ? '清空选择' : '全选照片'}
          </button>
        )}
      </div>
      {layouts.length > 1 && (
        <label className="viewer-tools">
          采集布局
          <select value={layout} onChange={(event) => showLayout(event.target.value)}>
            {layouts.map((key) => <option key={key} value={key}>{layoutTitle(key)}</option>)}
          </select>
        </label>
      )}
      {frames.length ? (
        <>
          {!readOnly && <p className="instructions">点击原图预览，按勾选顺序加入批次。</p>}
          <div className="frame-grid">
            {frames.map((f) => {
              const order = selected.indexOf(f.frame_id)
              return (
                <article
                  className={'frame' + (f.frame_id === previewId ? ' previewed' : '')}
                  key={f.frame_id}
                >
                  <button
                    className="thumb"
                    onClick={() => preview(f.frame_id)}
                    aria-label={'预览 ' + f.filename}
                  >
                    <img src={f.image_url} alt="" loading="lazy" />
                  </button>
                  {!readOnly && <label className={'pick' + (order >= 0 ? ' checked' : '')}>
                    <input
                      type="checkbox"
                      disabled={busy}
                      checked={order >= 0}
                      onChange={() => toggle(f.frame_id)}
                      aria-label={'加入批次 ' + f.filename}
                    />
                    <span aria-hidden="true">{order >= 0 ? order + 1 : ''}</span>
                  </label>}
                  <div className="frame-caption">
                    <strong title={f.filename}>{f.filename}</strong>
                    <small>{frameLabel(f.view_label)}</small>
                    {showUploads && (
                      <button className="text-button frame-history"
                        aria-label={f.filename + ' 的上传记录'} onClick={() => showUploads(f)}>
                        上传记录
                      </button>
                    )}
                  </div>
                </article>
              )
            })}
          </div>
          {!readOnly && <div className="batch-bar">
            <span>
              已选 <b>{selected.length}</b> 张
            </span>
            <button className="secondary" disabled={busy || !selected.length} onClick={freeze}>
              {busy ? '正在保存…' : '确认照片批次'}
            </button>
          </div>}
        </>
      ) : (
        <div className="empty gallery-empty">
          <span className="photo-glyph" aria-hidden="true" />
          <span>尚无采集照片</span>
        </div>
      )}
    </section>
  )
}
const statuses: Record<string, string> = {
  queued: '排队中',
  running: '处理中',
  succeeded: '已完成',
  success: '已完成',
  failed: '失败',
  cancelled: '已取消',
}
export function JobsPanel({
  frames,
  revisions,
  revisionLayouts,
  jobs,
  revisionId,
  choose,
  preview,
  enqueue,
  busy,
  readOnly,
}: {
  frames: Frame[]
  revisions: Revision[]
  revisionLayouts: Map<string, string>
  jobs: Job[]
  revisionId: string
  choose: (id: string) => void
  preview: (id: string) => void
  enqueue: (id: string, kind: Kind, recipeVersion: string) => Promise<void>
  busy: boolean
  readOnly: boolean
}) {
  const revision = revisions.find((item) => item.revision_id === revisionId) ?? revisions[0]
  const [mode, setMode] = useState<'points' | 'splat'>('points')
  const [splatRecipe, setSplatRecipe] = useState('v1')
  const kind = mode === 'splat' ? 'splat' : revision?.frame_ids.length === 1 ? 'depth' : 'fusion'
  const recipe = kind === 'splat' ? splatRecipe : 'v1'
  const frameCount = revision?.frame_ids.length ?? 0
  const invalidSplat = kind === 'splat' && (frameCount < 3 || (recipe === 'public-32-v1' && frameCount !== 32))
  const existing = jobs.find(
    (j) => j.revision_id === revision?.revision_id && j.kind === kind && j.recipe_version === recipe,
  )
  const results = jobs.filter(
    (job) => job.revision_id === revision?.revision_id
      && (job.status === 'succeeded' || job.status === 'failed'),
  )
  return (
    <div className="job-layout">
      <section className={'card' + (readOnly ? ' span-all' : '')}>
        <div className="card-heading">
          <h2>
            照片批次 <span className="counter">{revisions.length}</span>
          </h2>
        </div>
        {!revisions.length ? (
          <p className="empty">{readOnly ? '暂无照片批次' : '在采集照片中勾选原图，确认后会生成批次。'}</p>
        ) : (
          <ul className="revision-list">
            {revisions.map((r) => (
              <li key={r.revision_id}>
                <button
                  aria-pressed={r.revision_id === revision?.revision_id}
                  className={r.revision_id === revision?.revision_id ? 'active' : ''}
                  onClick={() => choose(r.revision_id)}
                >
                  <strong>批次 v{r.version}</strong>
                  <span>
                    {r.frame_ids.length} 张照片
                    {revisionLayouts.has(r.revision_id) && ` · ${layoutTitle(revisionLayouts.get(r.revision_id)!)}`}
                  </span>
                  <small>{timeLabel(r.created_at)}</small>
                </button>
              </li>
            ))}
          </ul>
        )}
        {revision && (
          <details className="batch-inputs">
            <summary>查看批次 v{revision.version} 的原图顺序</summary>
            <ol>
              {revision.frame_ids.map((id) => {
                const frame = frames.find((f) => f.frame_id === id)
                return (
                  <li key={id}>
                    {frame ? (
                      <>
                        <a href={frame.image_url} target="_blank" rel="noreferrer">
                          {frame.filename}
                        </a>
                        <small>{frameLabel(frame.view_label)}</small>
                        <button className="text-button" onClick={() => preview(id)}>工作台预览</button>
                      </>
                    ) : (
                      id
                    )}
                  </li>
                )
              })}
            </ol>
          </details>
        )}
      </section>
      {!readOnly && <section className="card form-card">
        <div className="card-heading">
          <h2>提交处理任务</h2>
        </div>
        <div className="form-body">
          <div className="meta-pair">
            <span>输入批次</span>
            <strong>
              {revision
                ? 'v' + revision.version + ' · ' + revision.frame_ids.length + ' 张照片'
                : '待确认'}
            </strong>
          </div>
          <label>
            处理方式
            <select value={mode} onChange={(e) => setMode(e.target.value as 'points' | 'splat')}>
              <option value="points">
                {revision && revision.frame_ids.length > 1 ? '多图点云融合' : '深度与点云'}
              </option>
              <option value="splat">3DGS 实景重建</option>
            </select>
          </label>
          {kind === 'splat' ? (
            <>
              <label>
                重建配方
                <select value={splatRecipe} onChange={(e) => setSplatRecipe(e.target.value)}>
                  <option value="v1">普通重建</option>
                  <option value="public-32-v1">公开 32 图验收</option>
                </select>
              </label>
              <p className="hint">
                {recipe === 'public-32-v1'
                  ? '验收要求全部 32 张注册成功。'
                  : '至少需要 3 张不同照片，有效的部分配准也可以生成结果。'}
              </p>
            </>
          ) : (
            <p className="hint">点云任务会生成 GLB 和逐张深度预览。</p>
          )}
          <button
            className="primary"
            disabled={!revision || busy || !!existing || invalidSplat}
            onClick={() => revision && void enqueue(revision.revision_id, kind, recipe)}
          >
            {busy ? '正在提交…' : existing ? '该任务已提交' : '提交任务'}
          </button>
        </div>
      </section>}
      {results.length > 0 && (
        <section className="card span-all">
          <div className="card-heading"><h2>批次 v{revision?.version} 的作业结果</h2></div>
          <div className="form-body">
            {results.map((job) => (
              <div className="splat-result" key={job.job_id}>
                <strong>
                  {job.kind === 'splat'
                    ? job.recipe_version === 'public-32-v1' ? '公开 32 图验收' : '普通重建'
                    : kinds[job.kind]}
                  {job.run_number !== undefined && ` · 第 ${job.run_number} 次运行`}
                </strong>
                {job.registration && (
                  <div className="hint">
                    已注册 {job.registration.registered_images}/{job.registration.total_images} 张
                    {job.registration.unregistered_frame_ids.length > 0 && (
                      <details>
                        <summary>查看未注册照片</summary>
                        <ul>
                          {job.registration.unregistered_frame_ids.map((id) => {
                            const frame = frames.find((item) => item.frame_id === id)
                            return <li key={id}>{frame ? frame.filename + ' · ' + frame.view_label : id}</li>
                          })}
                        </ul>
                      </details>
                    )}
                  </div>
                )}
                {job.error_message && <p className="error">{job.error_message}（{job.error_code}）</p>}
                {job.artifacts?.map((artifact) => (
                  <a key={artifact.filename} href={artifact.url} download>{artifact.filename}</a>
                ))}
              </div>
            ))}
          </div>
        </section>
      )}
      <section className="card span-all">
        <div className="card-heading">
          <h2>
            任务队列 <span className="counter">{jobs.length}</span>
          </h2>
        </div>
        {jobs.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>处理任务</th>
                  <th>照片批次</th>
                  <th>提交时间</th>
                  <th>状态</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((j) => (
                  <tr key={j.job_id}>
                    <td>{kinds[j.kind] ?? j.kind}</td>
                    <td>
                      v{revisions.find((r) => r.revision_id === j.revision_id)?.version ?? '—'}
                    </td>
                    <td>{timeLabel(j.created_at)}</td>
                    <td>
                      <span className="job-status">{statuses[j.status] ?? j.status}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="empty">暂无处理任务</p>
        )}
      </section>
    </div>
  )
}
