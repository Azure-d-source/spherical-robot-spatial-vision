import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const manifest = JSON.parse(
  await readFile(new URL('../dist/.vite/manifest.json', import.meta.url)),
)
const three = Object.keys(manifest).find(
  (key) => manifest[key].name === 'three',
)
assert(three, 'Missing separate Three.js chunk')

function staticImports(entry, visited = new Set()) {
  if (visited.has(entry)) return visited
  visited.add(entry)
  for (const dependency of manifest[entry].imports ?? [])
    staticImports(dependency, visited)
  return visited
}

assert(
  !staticImports('index.html').has(three),
  'Three.js is in the workbench startup graph',
)
for (const viewer of ['PointCloudViewer.tsx', 'VirtualCameraCanvas.tsx']) {
  const entry = Object.keys(manifest).find((key) => key.endsWith('/' + viewer))
  assert(
    entry && manifest[entry].isDynamicEntry,
    viewer + ' must be dynamically loaded',
  )
  assert(
    staticImports(entry).has(three),
    viewer + ' must use the separate Three.js chunk',
  )
}
console.log(
  'Viewer bundles checked. Three.js loads only with the point cloud or virtual camera.',
)
