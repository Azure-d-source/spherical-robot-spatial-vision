import { useEffect, useRef, useState } from 'react'
import {
  Box3,
  Color,
  PerspectiveCamera,
  Points,
  PointsMaterial,
  Scene,
  Sphere,
  Vector3,
  WebGLRenderer,
} from 'three'
import type { Object3D } from 'three'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { disposeObjects } from './resources'

export default function PointCloudViewer({ url }: { url: string }) {
  const container = useRef<HTMLDivElement>(null)
  const actions = useRef<{
    resizePoints: (size: number) => void
    reset: () => void
  }>(null)
  const [size, setSize] = useState(2)
  const sizeRef = useRef(2)
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')

  useEffect(() => {
    const host = container.current
    if (!host) return
    let renderer: WebGLRenderer
    try {
      renderer = new WebGLRenderer({ antialias: true })
    } catch {
      setStatus('error')
      return
    }
    const abort = new AbortController()
    const scene = new Scene()
    scene.background = new Color('#131f2a')
    const camera = new PerspectiveCamera(50)
    const controls = new OrbitControls(camera, renderer.domElement)
    const materials = new Set<PointsMaterial>()
    let model: Object3D | undefined
    let bounds: Sphere | undefined
    host.appendChild(renderer.domElement)
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))

    function render() {
      renderer.render(scene, camera)
    }

    function reset() {
      if (!bounds) return
      const halfFov = Math.atan(
        Math.tan((camera.fov * Math.PI) / 360) * Math.min(camera.aspect, 1),
      )
      const radius = Math.max(bounds.radius, 1e-4)
      const distance = (radius / Math.sin(halfFov)) * 1.1
      camera.near = radius / 1000
      camera.far = distance + radius * 50
      camera.updateProjectionMatrix()
      controls.target.copy(bounds.center)
      camera.position
        .copy(bounds.center)
        .addScaledVector(new Vector3(1, 0.55, 1.5).normalize(), distance)
      controls.minDistance = radius / 30
      controls.maxDistance = distance + radius * 30
      controls.update()
      render()
    }

    function resizePoints(next: number) {
      materials.forEach((material) => {
        material.size = next
        material.sizeAttenuation = false
      })
      render()
    }

    function resize() {
      if (!host) return
      const width = Math.max(host.clientWidth, 1)
      const height = Math.max(host.clientHeight, 1)
      camera.aspect = width / height
      camera.updateProjectionMatrix()
      renderer.setSize(width, height, false)
      render()
    }

    const observer = new ResizeObserver(resize)
    observer.observe(host)
    controls.addEventListener('change', render)
    actions.current = { resizePoints, reset }
    resize()
    setStatus('loading')

    async function load() {
      try {
        const source = new URL(url, location.origin)
        if (source.origin !== location.origin)
          throw new Error('Unsupported point cloud URL')
        const response = await fetch(source, { signal: abort.signal })
        if (!response.ok) throw new Error('Could not load point cloud')
        const { scene: root } = await new GLTFLoader().parseAsync(
          await response.arrayBuffer(),
          new URL('.', source).href,
        )
        if (abort.signal.aborted) {
          disposeObjects(root)
          return
        }
        model = root
        root.traverse((object) => {
          if (!(object instanceof Points)) return
          const values = Array.isArray(object.material)
            ? object.material
            : [object.material]
          values.forEach((material) => {
            if (material instanceof PointsMaterial) materials.add(material)
          })
        })
        const box = new Box3().setFromObject(root)
        if (!materials.size || box.isEmpty())
          throw new Error('No point primitives')
        bounds = box.getBoundingSphere(new Sphere())
        if (!Number.isFinite(bounds.radius))
          throw new Error('Invalid point cloud bounds')
        scene.add(root)
        resizePoints(sizeRef.current)
        reset()
        setStatus('ready')
      } catch {
        if (!abort.signal.aborted) setStatus('error')
      }
    }
    void load()

    return () => {
      abort.abort()
      actions.current = null
      observer.disconnect()
      controls.removeEventListener('change', render)
      controls.dispose()
      if (model) disposeObjects(model)
      renderer.dispose()
      renderer.forceContextLoss()
      renderer.domElement.remove()
    }
  }, [url])

  return (
    <>
      <div
        className="viewer-graphics"
        aria-label="可旋转的三维点云"
        ref={container}
      >
        {status !== 'ready' && (
          <div
            className="viewer-overlay"
            role={status === 'error' ? 'alert' : 'status'}
          >
            {status === 'error'
              ? '点云无法打开，请检查 GLB 文件或浏览器 WebGL 支持。'
              : '正在加载点云…'}
          </div>
        )}
      </div>
      <div className="viewer-tools">
        <label>
          点尺寸
          <input
            type="range"
            min="1"
            max="12"
            value={size}
            disabled={status !== 'ready'}
            onChange={(event) => {
              const value = Number(event.target.value)
              sizeRef.current = value
              setSize(value)
              actions.current?.resizePoints(value)
            }}
          />
          <output>{size} px</output>
        </label>
        <button
          className="secondary"
          disabled={status !== 'ready'}
          onClick={() => actions.current?.reset()}
        >
          重置视角
        </button>
        <span className="hint">拖动旋转 · 滚轮缩放</span>
      </div>
    </>
  )
}
