import { lazy, Suspense, useId } from 'react'
import type { KeyboardEvent } from 'react'
import { Viewport } from '../../Panels'
import type { Frame, Job, Revision } from '../../api'
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

type Props = {
  sceneId: string
  revision?: Revision
  revisions: Revision[]
  jobs: Job[]
  frame?: Frame
  view: string
  mode: ViewerMode
  className?: string
  onMode: (mode: ViewerMode) => void
  onRevision: (id: string) => void
  onCaptured: (frame: Frame) => void
  resetFrame: () => void
}

function findViewableResults(jobs: Job[], revision: Revision | undefined) {
  const available = jobs.filter(
    (job) =>
      job.revision_id === revision?.revision_id && job.status === 'succeeded',
  )
  const point = available.find((job) =>
    job.artifacts?.some((file) => file.filename === 'scene.glb'),
  )
  const splat =
    available.find((job) =>
      job.artifacts?.some((file) => file.filename === 'scene.sog'),
    ) ??
    available.find((job) =>
      job.artifacts?.some((file) => file.filename === 'scene.ply'),
    )
  return {
    points: point?.artifacts?.find((file) => file.filename === 'scene.glb')
      ?.url,
    splats: ['scene.sog', 'scene.ply'].flatMap((name) => {
      const file = splat?.artifacts?.find(
        (artifact) => artifact.filename === name,
      )
      return file ? [file.url] : []
    }),
  }
}

export function ViewerStage({
  sceneId,
  revision,
  revisions,
  jobs,
  frame,
  view,
  mode,
  className,
  onMode,
  onRevision,
  onCaptured,
  resetFrame,
}: Props) {
  const id = useId()
  const assets = findViewableResults(jobs, revision)

  function moveTab(
    event: KeyboardEvent<HTMLButtonElement>,
    current: ViewerMode,
  ) {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
    event.preventDefault()
    const index = tabs.findIndex((tab) => tab.id === current)
    const next =
      event.key === 'Home'
        ? tabs[0]
        : event.key === 'End'
          ? tabs[tabs.length - 1]
          : tabs[
              (index + (event.key === 'ArrowLeft' ? -1 : 1) + tabs.length) %
                tabs.length
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
          {tabs.map((tab) => (
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
                </option>
              ))}
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
            (assets.points ? (
              <PointCloudViewer key={assets.points} url={assets.points} />
            ) : (
              <p className="viewer-empty">
                当前批次暂无点云。提交深度或点云融合任务后，结果会显示在这里。
              </p>
            ))}
          {mode === 'splat' &&
            (assets.splats.length ? (
              <SuperSplatFrame
                key={assets.splats.join(',')}
                urls={assets.splats}
              />
            ) : (
              <p className="viewer-empty">
                当前批次暂无 3DGS。提交实景重建任务后，结果会显示在这里。
              </p>
            ))}
          {mode === 'virtual' && (
            <VirtualCameraCanvas sceneId={sceneId} onCaptured={onCaptured} />
          )}
        </Suspense>
      </div>
    </section>
  )
}
