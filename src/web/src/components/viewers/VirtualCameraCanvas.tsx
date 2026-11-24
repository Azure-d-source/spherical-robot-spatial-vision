import { useEffect, useRef, useState } from 'react'
import {
  MathUtils,
  PCFShadowMap,
  PerspectiveCamera,
  WebGLRenderer,
} from 'three'
import { api, errorText } from '../../api'
import type { Frame } from '../../api'
import { disposeObjects } from './resources'
import { createVirtualScene } from './virtualScene'

const presets = [
  { label: '正面', azimuth: 0, elevation: 17, distance: 5.4 },
  { label: '左侧', azimuth: -58, elevation: 20, distance: 5.4 },
  { label: '背面', azimuth: 180, elevation: 19, distance: 5.4 },
  { label: '右侧', azimuth: 58, elevation: 20, distance: 5.4 },
  { label: '顶部', azimuth: 15, elevation: 78, distance: 5.8 },
]
type Pose = (typeof presets)[number]
const adjustments = [
  { key: 'azimuth', label: '方位', min: -180, max: 180, step: 1, unit: '°' },
  { key: 'elevation', label: '仰角', min: 4, max: 85, step: 1, unit: '°' },
  { key: 'distance', label: '距离', min: 3.5, max: 8, step: 0.1, unit: '' },
] as const

export default function VirtualCameraCanvas({
  sceneId,
  onCaptured,
}: {
  sceneId: string
  onCaptured: (frame: Frame) => void
}) {
  const container = useRef<HTMLDivElement>(null)
  const poseRef = useRef(presets[0])
  const handle = useRef<{ canvas: HTMLCanvasElement; draw: () => void }>(null)
  const [pose, setPose] = useState(presets[0])
  const [ready, setReady] = useState(false)
  const [busy, setBusy] = useState(false)
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
    const { scene, light } = createVirtualScene()
    const camera = new PerspectiveCamera(44, 1, 0.1, 40)
    host.appendChild(canvas)
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5))
    renderer.shadowMap.enabled = true
    renderer.shadowMap.type = PCFShadowMap

    function draw() {
      const { azimuth, elevation, distance } = poseRef.current
      const heading = MathUtils.degToRad(azimuth)
      const angle = MathUtils.degToRad(elevation)
      const horizontal = distance * Math.cos(angle)
      camera.position.set(
        horizontal * Math.sin(heading),
        0.95 + distance * Math.sin(angle),
        horizontal * Math.cos(heading),
      )
      camera.lookAt(0, 0.95, 0)
      renderer.render(scene, camera)
    }

    function resize() {
      if (!host) return
      const width = Math.max(host.clientWidth, 1)
      const height = Math.max(host.clientHeight, 1)
      camera.aspect = width / height
      camera.updateProjectionMatrix()
      renderer.setSize(width, height, false)
      draw()
    }

    const observer = new ResizeObserver(resize)
    observer.observe(host)
    handle.current = { canvas, draw }
    resize()
    setReady(true)
    return () => {
      handle.current = null
      observer.disconnect()
      disposeObjects(scene)
      light.shadow.dispose()
      renderer.dispose()
      renderer.forceContextLoss()
      canvas.remove()
    }
  }, [])

  function move(next: Pose) {
    poseRef.current = next
    setPose(next)
    handle.current?.draw()
  }

  async function capture() {
    const camera = handle.current
    if (!camera || busy) return
    setBusy(true)
    setError('')
    const captured = poseRef.current
    try {
      camera.draw()
      const blob = await new Promise<Blob>((resolve, reject) => {
        camera.canvas.toBlob(
          (image) =>
            image ? resolve(image) : reject(new Error('画布截图失败。')),
          'image/png',
        )
      })
      const bytes = crypto.getRandomValues(new Uint8Array(16))
      const id = Array.from(bytes, (byte) =>
        byte.toString(16).padStart(2, '0'),
      ).join('')
      const file = new File([blob], `virtual-${id.slice(0, 8)}.png`, {
        type: 'image/png',
      })
      const label =
        captured.label === '自定义'
          ? `自定义 ${captured.azimuth}°/${captured.elevation}°`
          : captured.label
      onCaptured(await api.upload(sceneId, file, label, id))
    } catch (failure) {
      setError(errorText(failure))
    } finally {
      setBusy(false)
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
              disabled={!ready}
              onClick={() => move(preset)}
            >
              {preset.label}
            </button>
          ))}
        </div>
        <button
          className="primary"
          disabled={!ready || busy}
          onClick={() => void capture()}
        >
          {busy ? '正在上传…' : '拍摄并上传'}
        </button>
      </div>
      <div className="viewer-tools camera-adjustments">
        {adjustments.map(({ key, label, min, max, step, unit }) => (
          <label key={key}>
            {label}
            <input
              type="range"
              min={min}
              max={max}
              step={step}
              value={pose[key]}
              disabled={!ready}
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
      {error && (
        <p className="viewer-message error" role="alert">
          {error}
        </p>
      )}
    </>
  )
}
