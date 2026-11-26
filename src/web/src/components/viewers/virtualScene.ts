import {
  BoxGeometry,
  CanvasTexture,
  Color,
  DirectionalLight,
  Group,
  HemisphereLight,
  Mesh,
  MeshStandardMaterial,
  PlaneGeometry,
  Scene,
  SphereGeometry,
  SRGBColorSpace,
} from 'three'
import type { Object3D } from 'three'
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js'

function texture(paint: (context: CanvasRenderingContext2D) => void) {
  const canvas = document.createElement('canvas')
  canvas.width = 512
  canvas.height = 512
  paint(canvas.getContext('2d')!)
  const result = new CanvasTexture(canvas)
  result.colorSpace = SRGBColorSpace
  return result
}

function grain(ctx: CanvasRenderingContext2D, seed: number, colors: string[]) {
  function random() {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0
    return seed / 4294967296
  }
  for (let i = 0; i < 3000; i++) {
    ctx.fillStyle = colors[i % colors.length]
    ctx.fillRect(random() * 512, random() * 512, 1 + random() * 8, 1 + random() * 3)
  }
}

function patternedMaterial(base: string, ink: string, tag: string, seed: number) {
  return new MeshStandardMaterial({
    roughness: 0.85,
    map: texture((ctx) => {
      ctx.fillStyle = base
      ctx.fillRect(0, 0, 512, 512)
      grain(ctx, seed, ['#ffffff35', '#13212d55', '#ffffff18'])
      ctx.strokeStyle = ink
      ctx.lineWidth = 12
      ctx.strokeRect(32, 28, 448, 456)
      ctx.strokeRect(66, 68, 176, 152)
      ctx.beginPath()
      ctx.moveTo(288, 85)
      ctx.lineTo(429, 85)
      ctx.lineTo(409, 164)
      ctx.lineTo(286, 188)
      ctx.stroke()
      ctx.fillStyle = ink
      ctx.font = '900 127px monospace'
      ctx.fillText(tag, 92, 385)
    }),
  })
}

export function createVirtualScene() {
  const scene = new Scene()
  scene.background = new Color('#8ba6ad')
  scene.add(new HemisphereLight('#e9fbff', '#b5a6a0', 2.1))
  const sun = new DirectionalLight('#fff0d1', 1.7)
  sun.position.set(-3, 7, 4)
  sun.castShadow = true
  sun.shadow.mapSize.set(1024, 1024)
  sun.shadow.camera.left = -5
  sun.shadow.camera.right = 5
  sun.shadow.camera.top = 5
  sun.shadow.camera.bottom = -5
  scene.add(sun)

  const tableMap = texture((ctx) => {
    ctx.fillStyle = '#a38061'
    ctx.fillRect(0, 0, 512, 512)
    const boards = ['#b08c6a', '#947251', '#ab8765', '#b59474']
    for (let row = 0; row < 8; row++) {
      ctx.fillStyle = boards[row % boards.length]
      ctx.fillRect(0, row * 64, 512, 63)
      ctx.strokeStyle = '#60483355'
      for (let i = 0; i < 8; i++) {
        const y = row * 64 + i * 7 + 3
        ctx.beginPath()
        ctx.moveTo(0, y)
        ctx.bezierCurveTo(130, y - 8, 320, y + 6, 512, y)
        ctx.stroke()
      }
    }
    grain(ctx, 78, ['#4b31274f', '#f1c58b67', '#61412b60'])
  })
  const tabletop = new Mesh(
    new PlaneGeometry(12, 12),
    new MeshStandardMaterial({ map: tableMap }),
  )
  tabletop.rotation.x = -Math.PI / 2
  tabletop.receiveShadow = true
  scene.add(tabletop)

  const matMap = texture((ctx) => {
    ctx.fillStyle = '#30525d'
    ctx.fillRect(0, 0, 512, 512)
    const colors = ['#436d70', '#345563', '#5b6673', '#46656a', '#705e53']
    for (let i = 0; i < 36; i++) {
      const x = 16 + (i % 6) * 80
      const y = 16 + Math.floor(i / 6) * 80
      ctx.fillStyle = colors[(i * 13 + Math.floor(i / 6)) % colors.length]
      ctx.fillRect(x, y, 77, 77)
      ctx.strokeStyle = '#b5b79a'
      ctx.lineWidth = 2
      ctx.strokeRect(x + 9, y + 10, 56 - (i % 5) * 5, 49 + (i % 4) * 5)
      ctx.font = 'bold 26px monospace'
      ctx.fillStyle = i % 4 ? '#d8d6ad' : '#ffd986'
      ctx.fillText(String.fromCharCode(65 + Math.floor(i / 6)) + (i % 6 + 1), x + 13, y + 38)
      ctx.fillRect(x + 46, y + 49, 6 + (i % 7) * 2, 4 + (i % 3) * 3)
    }
    grain(ctx, 202, ['#15242c44', '#ece9bf33', '#c0a2783f'])
    ctx.strokeStyle = '#dfc784'
    ctx.lineWidth = 4
    ctx.strokeRect(8, 8, 496, 496)
  })
  const mat = new Mesh(
    new PlaneGeometry(5.6, 5.6),
    new MeshStandardMaterial({ map: matMap }),
  )
  mat.rotation.x = -Math.PI / 2
  mat.position.y = 0.008
  mat.receiveShadow = true
  scene.add(mat)

  const toy = new Group()
  scene.add(toy)
  const teal = patternedMaterial('#297b74', '#92bfb1', 'R2', 54)
  const orange = patternedMaterial('#d58439', '#66391b', '+', 83)
  const dark = new MeshStandardMaterial({ color: '#263841' })
  const cream = patternedMaterial('#dfcfab', '#6f715e', '•', 26)

  function part(
    width: number,
    height: number,
    depth: number,
    material: MeshStandardMaterial,
    x: number,
    y: number,
    z: number,
    group: Object3D = toy,
  ) {
    const mesh = new Mesh(
      new RoundedBoxGeometry(width, height, depth, 3, 0.085),
      material,
    )
    mesh.position.set(x, y, z)
    mesh.castShadow = true
    mesh.receiveShadow = true
    group.add(mesh)
    return mesh
  }

  part(1.03, 0.9, 0.72, teal, 0, 0.88, 0)
  part(0.92, 0.61, 0.7, cream, 0, 1.62, 0)
  part(0.16, 0.22, 0.16, dark, 0.2, 2.0, 0)
  const beacon = new Mesh(new SphereGeometry(0.13, 20, 12), orange)
  beacon.position.set(0.2, 2.14, 0)
  toy.add(beacon)
  for (const side of [-1, 1]) {
    const arm = part(0.26, 0.62, 0.33, orange, side * 0.66, 0.94, 0)
    arm.rotation.z = side * 0.19
    part(0.29, 0.39, 0.43, dark, side * 0.28, 0.36, 0)
    part(0.36, 0.19, 0.6, teal, side * 0.28, 0.12, 0.1)
    part(0.12, 0.27, 0.34, teal, side * 0.49, 1.63, 0)
  }

  function panel(
    map: CanvasTexture,
    width: number,
    height: number,
    y: number,
    z: number,
  ) {
    const mesh = new Mesh(
      new PlaneGeometry(width, height),
      new MeshStandardMaterial({ map }),
    )
    mesh.position.set(0, y, z)
    if (z < 0) mesh.rotation.y = Math.PI
    toy.add(mesh)
  }

  panel(
    texture((ctx) => {
      ctx.fillStyle = '#172d37'
      ctx.fillRect(0, 0, 512, 512)
      ctx.fillStyle = '#89e8cb'
      ctx.beginPath()
      ctx.roundRect(110, 132, 100, 155, 26)
      ctx.roundRect(304, 132, 100, 155, 26)
      ctx.fill()
      ctx.fillRect(213, 365, 86, 16)
    }),
    0.71,
    0.43,
    1.63,
    0.352,
  )
  panel(
    texture((ctx) => {
      ctx.fillStyle = '#742049'
      ctx.fillRect(0, 0, 512, 512)
      ctx.fillStyle = '#201933'
      ctx.fillRect(15, 20, 482, 472)
      ctx.fillStyle = '#ffe253'
      ctx.beginPath()
      ctx.moveTo(254, 35)
      ctx.lineTo(477, 141)
      ctx.lineTo(447, 397)
      ctx.lineTo(254, 477)
      ctx.lineTo(64, 397)
      ctx.lineTo(34, 141)
      ctx.closePath()
      ctx.fill()
      ctx.fillStyle = '#201933'
      ctx.font = '900 207px monospace'
      ctx.textAlign = 'center'
      ctx.fillText('07', 254, 338)
      ctx.fillStyle = '#be255e'
      ctx.fillRect(202, 129, 104, 34)
      ctx.fillRect(209, 372, 90, 30)
    }),
    0.89,
    0.72,
    0.88,
    -0.362,
  )

  // Fixed landmarks keep nearby camera views visually distinct and overlapping.
  const box = patternedMaterial('#975545', '#f2cc99', 'K4', 59)
  const book = patternedMaterial('#536698', '#f4dfa7', 'M8', 117)
  const tray = patternedMaterial('#5d6544', '#dbbf79', 'P5', 242)
  part(0.62, 0.68, 0.8, box, -1.92, 0.35, -1.42, scene).rotation.y = 0.27
  part(0.84, 0.3, 0.61, book, 1.96, 0.16, -1.3, scene).rotation.y = -0.47
  part(0.66, 0.18, 0.54, tray, 1.64, 0.1, 1.58, scene).rotation.y = 0.2
  const tile = new Mesh(
    new BoxGeometry(0.68, 0.06, 0.7),
    patternedMaterial('#678d8f', '#282c3e', 'L3', 72),
  )
  tile.position.set(-1.94, 0.04, 1.36)
  tile.rotation.y = 0.35
  scene.add(tile)
  return { scene, light: sun, toy }
}
