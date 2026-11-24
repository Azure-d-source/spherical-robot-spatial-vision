import { useEffect, useRef, useState } from 'react'
import {
  MathUtils,
  PCFShadowMap,
  PerspectiveCamera,
  WebGLRenderer,
} from 'three'
import { api, errorText } from '../../api'
import type { Frame } from '../../api'
import { layoutKey, layoutTitle } from '../../simulationLayout'
import type { SimulationLayout } from '../../simulationLayout'
import { disposeObjects } from './resources'
import { createVirtualScene } from './virtualScene'

const width = 960
const height = 720
const distance = 4.25
const presets = [
  { label: '正面', azimuth: 0, elevation: 21, distance },
  { label: '左侧', azimuth: -90, elevation: 24, distance },
  { label: '背面', azimuth: 180, elevation: 21, distance },
  { label: '右侧', azimuth: 90, elevation: 24, distance },
  { label: '顶部', azimuth: 15, elevation: 78, distance },
]
type Pose = (typeof presets)[number]
const ring = Array.from({ length: 24 }, (_, index) => {
  const direction = ['正面', '右侧', '背面', '左侧'][Math.floor((index + 3) / 6) % 4]
  return {
    label: `环拍 ${String(index + 1).padStart(2, '0')} · ${direction}`,
    azimuth: ((index * 15 + 179) % 360) - 179,
    elevation: 21 + (index % 3) * 4,
    distance,
  }
})

const cameraAdjustments = [
  { key: 'azimuth', label: '球体绕行角度', min: -180, max: 180, step: 1, unit: '°' },
  { key: 'elevation', label: '机位高度角', min: 4, max: 85, step: 1, unit: '°' },
  { key: 'distance', label: '球体距离', min: 3.5, max: 8, step: 0.05, unit: '' },
] as const
const exhibitAdjustments = [
  { key: 'x', label: '展品横移', min: -0.7, max: 0.7, step: 0.05, unit: '' },
  { key: 'z', label: '展品纵移', min: -0.7, max: 0.7, step: 0.05, unit: '' },
  { key: 'rotation', label: '展品旋转', min: -180, max: 180, step: 5, unit: '°' },
] as const

export default function VirtualCameraCanvas({
  sceneId,
  layout,
  onLayout,
  onCaptured,
}: {
  sceneId: string
  layout: SimulationLayout
  onLayout: (layout: SimulationLayout) => void
  onCaptured: (frames: Frame[]) => void
}) {
  const container = useRef<HTMLDivElement>(null)
  const poseRef = useRef(presets[0])
  const handle = useRef<{
    canvas: HTMLCanvasElement
    draw: (layout: SimulationLayout) => void
  }>(null)
  const capturing = useRef(false)
  const [pose, setPose] = useState(presets[0])
  const [ready, setReady] = useState(false)
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    const host = container.current
    if (!host) return
    const canvas = document.createElement('canvas')
    let renderer: WebGLRenderer
    try {
      const context = canvas.getContext('webgl2', {
        alpha: false,
        antialias: true,
        preserveDrawingBuffer: true,
      })
      if (!context) throw new Error('WebGL2 unavailable')
      renderer = new WebGLRenderer({ canvas, context })
    } catch {
      setError('无法启动虚拟相机，请检查浏览器 WebGL 支持。')
      return
    }
    const { scene, light, toy } = createVirtualScene()
    const camera = new PerspectiveCamera(40, width / height, 0.1, 40)
    host.appendChild(canvas)
    renderer.setSize(width, height, false)
    renderer.shadowMap.enabled = true
    renderer.shadowMap.type = PCFShadowMap

    function draw(layout: SimulationLayout) {
      const { azimuth, elevation, distance } = poseRef.current
      const heading = MathUtils.degToRad(azimuth)
      const angle = MathUtils.degToRad(elevation)
      const horizontal = distance * Math.cos(angle)
      toy.position.set(layout.x, 0, layout.z)
      toy.rotation.y = MathUtils.degToRad(layout.rotation)
      // Use the ball's table position as the origin of the virtual camera mount.
      const ballX = layout.x + horizontal * Math.sin(heading)
      const ballZ = layout.z + horizontal * Math.cos(heading)
      camera.position.set(
        ballX,
        1.05 + distance * Math.sin(angle),
        ballZ,
      )
      camera.lookAt(layout.x, 1.05, layout.z)
      renderer.render(scene, camera)
    }

    handle.current = { canvas, draw }
    setReady(true)
    return () => {
      handle.current = null
      disposeObjects(scene)
      light.shadow.dispose()
      renderer.dispose()
      renderer.forceContextLoss()
      canvas.remove()
    }
  }, [])

  useEffect(() => {
    handle.current?.draw(layout)
  }, [layout])

  function move(next: Pose) {
    poseRef.current = next
    setPose(next)
    handle.current?.draw(layout)
  }

  async function capture(sequence: Pose[]) {
    const camera = handle.current
    if (!camera || capturing.current) return
    capturing.current = true
    setBusy(true)
    setError('')
    const accepted: Frame[] = []
    try {
      for (const captured of sequence) {
        if (handle.current !== camera) break
        move(captured)
        setProgress(`正在拍摄并上传 ${accepted.length + 1}/${sequence.length}…`)
        const blob = await new Promise<Blob>((resolve, reject) => {
          camera.canvas.toBlob(
            (image) => image ? resolve(image) : reject(new Error('画布截图失败。')),
            'image/png',
          )
        })
        if (handle.current !== camera) break
        const bytes = crypto.getRandomValues(new Uint8Array(16))
        const id = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
        const file = new File([blob], `virtual-${id.slice(0, 8)}.png`, { type: 'image/png' })
        const { label, azimuth, elevation, distance } = captured
        accepted.push(await api.upload(
          sceneId, file,
          `[${layoutKey(layout)}] ${label} ${azimuth}°/${elevation}° @cam:${azimuth},${elevation},${Math.round(distance * 100)}`,
          id,
        ))
      }
    } catch (failure) {
      setError(errorText(failure))
    } finally {
      if (accepted.length) onCaptured(accepted)
      capturing.current = false
      setBusy(false)
      setProgress('')
    }
  }

  return (
    <>
      <div
        className="viewer-graphics virtual-graphics"
        ref={container}
        aria-label="虚拟相机实时取景"
      />
      <div className="viewer-tools">
        <div className="camera-presets" aria-label="虚拟机位">
          {presets.map((preset) => (
            <button
              key={preset.label}
              className="secondary"
              aria-pressed={preset.label === pose.label}
              disabled={!ready || busy}
              onClick={() => move(preset)}
            >
              {preset.label}
            </button>
          ))}
        </div>
        <button
          className="primary"
          disabled={!ready || busy}
          onClick={() => void capture([pose])}
        >
          拍摄并上传
        </button>
        <button className="primary" disabled={!ready || busy} onClick={() => void capture(ring)}>
          环拍并上传 24 张
        </button>
      </div>
      {progress && <p className="viewer-message" role="status">{progress}</p>}
      <div className="viewer-tools camera-adjustments">
        {cameraAdjustments.map(({ key, label, min, max, step, unit }) => (
          <label key={key}>
            {label}
            <input
              type="range"
              min={min}
              max={max}
              step={step}
              value={pose[key]}
              disabled={!ready || busy}
              onChange={(event) =>
                move({
                  ...pose,
                  label: '自定义',
                  [key]: Number(event.target.value),
                })
              }
            />
            <output>
              {pose[key]}
              {unit}
            </output>
          </label>
        ))}
      </div>
      <div className="viewer-tools camera-adjustments">
        <strong>{layoutTitle(layoutKey(layout))}</strong>
        {exhibitAdjustments.map(({ key, label, min, max, step, unit }) => (
          <label key={key}>
            {label}
            <input
              type="range"
              min={min}
              max={max}
              step={step}
              value={layout[key]}
              disabled={!ready || busy}
              onChange={(event) => onLayout({ ...layout, [key]: Number(event.target.value) })}
            />
            <output>{layout[key]}{unit}</output>
          </label>
        ))}
        <p className="hint">移动展品会切换采集布局。确认照片批次后，可在查看批次中回看原图与三维结果。</p>
      </div>
      {error && (
        <p className="viewer-message error" role="alert">
          {error}
        </p>
      )}
    </>
  )
}
