import { cp, writeFile } from 'node:fs/promises'
import { defaultSettings } from '@playcanvas/supersplat-viewer/settings'

const packageDirectory = new URL(
  '../node_modules/@playcanvas/supersplat-viewer/',
  import.meta.url,
)
const destination = new URL('../public/supersplat/', import.meta.url)
const assets = [
  'index.js',
  'index.css',
  'index.js.map',
  'gsaf-decoder.wasm',
  'zstd-decoder.wasm',
]

await Promise.all([
  ...assets.map((name) =>
    cp(new URL('public/' + name, packageDirectory), new URL(name, destination)),
  ),
  ...['LICENSE', 'THIRD_PARTY_NOTICES.md'].map((name) =>
    cp(new URL(name, packageDirectory), new URL(name, destination)),
  ),
  writeFile(
    new URL('settings.json', destination),
    JSON.stringify(defaultSettings('object')) + '\n',
  ),
])
