import { lazy, Suspense, useId, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { Viewport } from '../../Panels'
import { recipeLabel, timeLabel } from '../../api'
import type { Frame, Job, Revision } from '../../api'
import { layoutTitle } from '../../simulationLayout'
import type { SimulationLayout } from '../../simulationLayout'
import SuperSplatFrame from './SuperSplatFrame'

const PointCloudViewer = lazy(() => import('./PointCloudViewer'))
const VirtualCameraCanvas = lazy(() => import('./VirtualCameraCanvas'))

const tabs = [
  { id: 'camera', label: '2D 机位' },
  { id: 'points', label: '点云' },
  { id: 'splat', label: '3DGS' },
  { id: 'virtual', label: '虚拟相机' },
] as const
export type ViewerMode = (typeof tabs)[number]['id']
type ModelMode = Extract<ViewerMode, 'points' | 'splat'>

const modelFiles: Record<ModelMode, readonly string[]> = {
  points: ['scene.glb'],
  splat: ['scene.sog', 'scene.ply'],
}

type Props = {
  sceneId: string
  revision?: Revision
  revisions: Revision[]
  revisionLayouts: Map<string, string>
  jobs: Job[]
  frame?: Frame
  view: string
  mode: ViewerMode
  className?: string
  readOnly: boolean
  onMode: (mode: ViewerMode) => void
  onRevision: (id: string) => void
  layout: SimulationLayout
  onLayout: (layout: SimulationLayout) => void
  onCaptured: (frames: Frame[]) => void
  resetFrame: () => void
}

function availableRuns(jobs: Job[], revision: Revision | undefined, mode: ModelMode) {
  return jobs.filter(
    (job) =>
      job.revision_id === revision?.revision_id && job.status === 'succeeded'
      && job.artifacts?.some((file) => modelFiles[mode].includes(file.filename)),
  ).sort((a, b) => (b.run_number ?? 0) - (a.run_number ?? 0))
}

function historyLabel(job: Job) {
  const run = job.run_number === undefined ? '' : `第 ${job.run_number} 次 · `
  return run + recipeLabel(job) + ' · ' + timeLabel(job.created_at)
}

export function ViewerStage({
  sceneId,
  revision,
  revisions,
  revisionLayouts,
  jobs,
  frame,
  view,
  mode,
  className,
  readOnly,
  onMode,
  onRevision,
  layout,
  onLayout,
  onCaptured,
  resetFrame,
}: Props) {
  const id = useId()
  const [pinnedRuns, setPinnedRuns] = useState<Record<string, string>>({})
  const modelMode = mode === 'points' || mode === 'splat' ? mode : undefined
  const key = revision && modelMode ? `${revision.revision_id}:${modelMode}` : ''
  const runs = modelMode ? availableRuns(jobs, revision, modelMode) : []
  const latest = runs[0]
  const pinnedRun = runs.find((run) => run.job_id === pinnedRuns[key])
  const selectedRun = pinnedRun ?? latest
  const urls = modelMode && selectedRun ? modelFiles[modelMode].flatMap((name) => {
    const file = selectedRun.artifacts?.find((artifact) => artifact.filename === name)
    return file ? [file.url] : []
  }) : []
  const visibleTabs = readOnly ? tabs.filter((tab) => tab.id !== 'virtual') : tabs

  function selectRun(jobId: string) {
    setPinnedRuns((previous) => {
      const next = { ...previous }
      if (jobId) next[key] = jobId
      else delete next[key]
      return next
    })
  }

  function moveTab(
    event: KeyboardEvent<HTMLButtonElement>,
    current: ViewerMode,
  ) {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
    event.preventDefault()
    const index = visibleTabs.findIndex((tab) => tab.id === current)
    const next =
      event.key === 'Home'
        ? visibleTabs[0]
        : event.key === 'End'
          ? visibleTabs[visibleTabs.length - 1]
          : visibleTabs[
              (index + (event.key === 'ArrowLeft' ? -1 : 1) + visibleTabs.length) %
                visibleTabs.length
            ]
    onMode(next.id)
    document.getElementById(id + '-' + next.id)?.focus()
  }

  return (
    <section
      className={['card', 'viewer-stage', className].filter(Boolean).join(' ')}
      aria-label="查看与取景"
    >
      <div className="viewer-heading">
        <div className="viewer-tabs" role="tablist" aria-label="查看方式">
          {visibleTabs.map((tab) => (
            <button
              key={tab.id}
              id={id + '-' + tab.id}
              role="tab"
              type="button"
              aria-selected={tab.id === mode}
              aria-controls={id + '-panel'}
              tabIndex={tab.id === mode ? 0 : -1}
              onClick={() => onMode(tab.id)}
              onKeyDown={(event) => moveTab(event, tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>
        {revisions.length > 0 && (
          <label className="viewer-revision">
            查看批次
            <select
              value={revision?.revision_id ?? ''}
              onChange={(event) => onRevision(event.target.value)}
            >
              {revisions.map((item) => (
                <option key={item.revision_id} value={item.revision_id}>
                  v{item.version} · {item.frame_ids.length} 张
                  {revisionLayouts.has(item.revision_id) && ` · ${layoutTitle(revisionLayouts.get(item.revision_id)!)}`}
                </option>
              ))}
            </select>
          </label>
        )}
        {latest && (
          <label className="viewer-run">
            查看运行
            <select value={pinnedRun?.job_id ?? ''} onChange={(event) => selectRun(event.target.value)}>
              <option value="">
                最新成功结果{latest.run_number !== undefined && ` · 第 ${latest.run_number} 次`}
              </option>
              {runs.map((job) => <option key={job.job_id} value={job.job_id}>{historyLabel(job)}</option>)}
            </select>
          </label>
        )}
      </div>
      <div role="tabpanel" id={id + '-panel'} aria-labelledby={id + '-' + mode}>
        <Suspense
          fallback={
            <p className="viewer-empty" role="status">
              正在加载查看模块…
            </p>
          }
        >
          {mode === 'camera' && (
            <Viewport frame={frame} view={view} reset={resetFrame} />
          )}
          {mode === 'points' &&
            (urls[0] ? (
              <PointCloudViewer key={urls[0]} url={urls[0]} />
            ) : (
              <p className="viewer-empty">
                {readOnly ? '当前批次暂无点云。' : '当前批次暂无点云。提交深度或点云融合任务后，结果会显示在这里。'}
              </p>
            ))}
          {mode === 'splat' &&
            (urls.length ? (
              <SuperSplatFrame
                key={urls.join(',')}
                urls={urls}
              />
            ) : (
              <p className="viewer-empty">
                {readOnly ? '当前批次暂无 3DGS。' : '当前批次暂无 3DGS。提交实景重建任务后，结果会显示在这里。'}
              </p>
            ))}
          {mode === 'virtual' && !readOnly && (
            <VirtualCameraCanvas sceneId={sceneId} layout={layout} onLayout={onLayout} onCaptured={onCaptured} />
          )}
        </Suspense>
      </div>
    </section>
  )
}
