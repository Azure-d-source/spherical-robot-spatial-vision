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

export function createVirtualScene() {
  const scene = new Scene()
  scene.background = new Color('#8ba6ad')
  scene.add(new HemisphereLight('#e9fbff', '#96826b', 2.4))
  const sun = new DirectionalLight('#fff0d1', 2.2)
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
  })
  const tabletop = new Mesh(
    new PlaneGeometry(12, 12),
    new MeshStandardMaterial({ map: tableMap }),
  )
  tabletop.rotation.x = -Math.PI / 2
  tabletop.receiveShadow = true
  scene.add(tabletop)

  const matMap = texture((ctx) => {
    ctx.fillStyle = '#284e52'
    ctx.fillRect(0, 0, 512, 512)
    ctx.strokeStyle = '#639290'
    ctx.lineWidth = 2
    for (let i = 16; i < 512; i += 32) {
      for (let j = 16; j < 512; j += 32) ctx.strokeRect(i - 1, j - 1, 2, 2)
    }
    ctx.lineWidth = 6
    ctx.strokeRect(20, 20, 472, 472)
    ctx.strokeStyle = '#ffcb84'
    ctx.beginPath()
    ctx.moveTo(256, 37)
    ctx.lineTo(240, 63)
    ctx.lineTo(272, 63)
    ctx.closePath()
    ctx.stroke()
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
  const teal = new MeshStandardMaterial({ color: '#297b74', roughness: 0.57 })
  const orange = new MeshStandardMaterial({ color: '#d58439' })
  const dark = new MeshStandardMaterial({ color: '#263841' })
  const cream = new MeshStandardMaterial({ color: '#efe0b8' })

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
      ctx.fillStyle = '#efb55e'
      ctx.fillRect(0, 0, 512, 512)
      ctx.fillStyle = '#2b3739'
      ctx.fillRect(30, 26, 452, 86)
      ctx.fillRect(30, 399, 452, 86)
      ctx.font = 'bold 160px system-ui'
      ctx.textAlign = 'center'
      ctx.fillText('B–07', 256, 316)
    }),
    0.71,
    0.5,
    0.91,
    -0.362,
  )

  // Fixed landmarks keep nearby camera views visually distinct and overlapping.
  part(0.56, 0.54, 0.8, orange, -1.7, 0.28, -1.1, scene)
  part(0.68, 0.28, 0.51, cream, 1.67, 0.15, -0.7, scene)
  part(0.57, 0.17, 0.36, dark, 1.15, 0.096, 1.27, scene)
  const ring = new Mesh(
    new BoxGeometry(0.68, 0.06, 0.7),
    new MeshStandardMaterial({ color: '#639f92' }),
  )
  ring.position.set(-1.4, 0.04, 1.35)
  ring.rotation.y = 0.35
  scene.add(ring)
  return { scene, light: sun }
}
