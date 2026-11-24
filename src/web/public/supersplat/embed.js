import { createViewer } from './index.js'

const stage = document.getElementById('viewer')
const query = new URLSearchParams(location.search)
const content = new URL(query.get('content') ?? '', location.origin)
let viewer
let disposed = false

function report(status) {
  stage.dataset.status = status
  window.parent.postMessage(
    { type: 'orbitforge:splat', status },
    location.origin,
  )
}

function dispose() {
  disposed = true
  viewer?.destroy()
}

addEventListener('pagehide', dispose, { once: true })
addEventListener('message', (event) => {
  if (
    event.origin === location.origin &&
    event.source === window.parent &&
    event.data?.type === 'orbitforge:dispose-splat'
  )
    dispose()
})

async function readCamera() {
  try {
    const response = await fetch(new URL('manifest.json', content))
    if (!response.ok) return null
    const { viewer_camera: camera } = await response.json()
    const validVector = (value) =>
      Array.isArray(value) && value.length === 3 && value.every(Number.isFinite)
    if (validVector(camera?.position) && validVector(camera.target) && camera.fov === 40)
      return camera
  } catch {
    // Previously published assets can still be framed from their bounds.
  }
  return null
}

try {
  if (
    content.origin !== location.origin ||
    !/^\/api\/artifacts\/[\w-]+\/scene\.(sog|ply)$/.test(content.pathname)
  ) {
    throw new Error('Unsupported scene URL')
  }
  const [response, camera] = await Promise.all([fetch(content), readCamera()])
  if (!response.ok) throw new Error('Could not download scene')
  const settings = camera
    ? fetch('./settings.json').then((response) => response.json()).then((defaults) => ({
        ...defaults,
        cameras: [{ initial: camera }],
      }))
    : './settings.json'
  if (!disposed) {
    viewer = await createViewer({
      container: stage,
      settings,
      contentUrl: content.href,
      contents: Promise.resolve(response),
      renderer: query.has('webgl') ? 'webgl' : 'webgpu',
      lang: 'zh-CN',
      noanim: true,
    })
    function showScene() {
      if (disposed) return
      if (camera) viewer.resetCamera()
      else viewer.frameScene()
      report('ready')
    }
    if (disposed) viewer?.destroy()
    else if (viewer.state.loaded) showScene()
    else viewer.events.once('loaded:changed', showScene)
  }
} catch (error) {
  console.error('SuperSplat could not initialize', error)
  if (!disposed) report('error')
}
