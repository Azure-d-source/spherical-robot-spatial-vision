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

try {
  if (
    content.origin !== location.origin ||
    !/^\/api\/artifacts\/[\w-]+\/scene\.(sog|ply)$/.test(content.pathname)
  ) {
    throw new Error('Unsupported scene URL')
  }
  const response = await fetch(content)
  if (!response.ok) throw new Error('Could not download scene')
  if (!disposed) {
    viewer = await createViewer({
      container: stage,
      settings: './settings.json',
      contentUrl: content.href,
      contents: Promise.resolve(response),
      renderer: query.has('webgl') ? 'webgl' : 'webgpu',
      lang: 'zh-CN',
      noanim: true,
    })
    function showScene() {
      if (disposed) return
      viewer.frameScene()
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
