import { useEffect, useRef } from 'react'

// Orthographic reference drawing. All coordinates are schematic and carry no device pose data.
export function OrbitView({ view }: { view: string }) {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    function draw() {
      if (!canvas || !ctx) return
      const w = canvas.clientWidth
      const h = canvas.clientHeight
      if (!w || !h) return
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      canvas.width = Math.round(w * dpr)
      canvas.height = Math.round(h * dpr)
      ctx.scale(dpr, dpr)
      type Point = [number, number, number]
      const zoom = Math.min(w / 6, h / 3.65)
      const ox = w / 2,
        oy = h * 0.66
      const yaw = 0.54,
        tilt = 0.38
      function project([x, y, z]: Point) {
        const horizontal = x * Math.cos(yaw) - z * Math.sin(yaw)
        const depth = x * Math.sin(yaw) + z * Math.cos(yaw)
        return [ox + horizontal * zoom, oy + (depth * Math.sin(tilt) - y * Math.cos(tilt)) * zoom]
      }
      function line(points: Point[], color: string, width = 1) {
        if (!ctx || points.length < 2) return
        ctx.beginPath()
        points.forEach((p, i) => {
          const [x, y] = project(p)
          if (i === 0) ctx.moveTo(x, y)
          else ctx.lineTo(x, y)
        })
        ctx.strokeStyle = color
        ctx.lineWidth = width
        ctx.stroke()
      }
      const tau = Math.PI * 2
      for (let n = -10; n <= 10; n++) {
        const v = n * 0.5
        line(
          [
            [v, 0, -5],
            [v, 0, 5],
          ],
          'rgba(122, 162, 176, .09)',
        )
        line(
          [
            [-5, 0, v],
            [5, 0, v],
          ],
          'rgba(122, 162, 176, .09)',
        )
      }
      const orbit = (radius: number, level: number): Point[] =>
        Array.from({ length: 97 }, (_, i) => [
          radius * Math.cos((i * tau) / 96),
          level,
          radius * Math.sin((i * tau) / 96),
        ])
      ctx.setLineDash([4, 5])
      line(orbit(1.78, 0.1), '#528785')
      ctx.setLineDash([])
      const sphere = (a: number, b: number): Point => {
        const r = 0.73
        return [r * Math.cos(a) * Math.cos(b), r + r * Math.sin(b), r * Math.sin(a) * Math.cos(b)]
      }
      const [cx, cy] = project([0, 0.73, 0])
      const radius = zoom * 0.73
      const fill = ctx.createRadialGradient(
        cx - radius * 0.35,
        cy - radius * 0.6,
        1,
        cx,
        cy,
        radius,
      )
      fill.addColorStop(0, '#294d53')
      fill.addColorStop(1, '#172b38')
      ctx.fillStyle = fill
      ctx.beginPath()
      ctx.arc(cx, cy, radius, 0, tau)
      ctx.fill()
      function visible(p: Point) {
        return (
          (p[0] * Math.sin(yaw) + p[2] * Math.cos(yaw)) * Math.cos(tilt) +
            (p[1] - 0.73) * Math.sin(tilt) >=
          0
        )
      }
      function surface(points: Point[]) {
        let visiblePoints: Point[] = []
        for (const p of points) {
          if (visible(p)) visiblePoints.push(p)
          else if (visiblePoints.length) {
            line(visiblePoints, '#44817e', 0.8)
            visiblePoints = []
          }
        }
        line(visiblePoints, '#44817e', 0.8)
      }
      for (let i = 0; i < 18; i++)
        surface(
          Array.from({ length: 65 }, (_, j) => sphere((i * tau) / 18, (j / 64 - 0.5) * Math.PI)),
        )
      for (let i = -4; i <= 4; i++)
        surface(Array.from({ length: 97 }, (_, j) => sphere((j * tau) / 96, (i * Math.PI) / 10)))
      ctx.strokeStyle = '#69a6a0'
      ctx.beginPath()
      ctx.arc(cx, cy, radius, 0, tau)
      ctx.stroke()
      const places: [string, Point][] = [
        ['正面', [0, 0.1, 1.78]],
        ['右侧', [1.78, 0.1, 0]],
        ['背面', [0, 0.1, -1.78]],
        ['左侧', [-1.78, 0.1, 0]],
        ['顶部', [0, 1.93, 0]],
      ]
      for (const [label, point] of places) {
        const active = label === view
        const [x, y] = project(point)
        ctx.fillStyle = active ? '#69edc5' : '#263c49'
        ctx.strokeStyle = active ? '#9dffdf' : '#67818c'
        ctx.beginPath()
        ctx.arc(x, y, active ? 4.5 : 3, 0, tau)
        ctx.fill()
        ctx.stroke()
        const dy = label === '顶部' || label === '背面' ? -11 : 20
        ctx.font = '12px system-ui, sans-serif'
        ctx.textAlign = 'center'
        ctx.fillStyle = active ? '#9af3d7' : '#95aab3'
        ctx.fillText(label, x, y + dy)
      }
    }
    const observer = new ResizeObserver(draw)
    observer.observe(canvas)
    draw()
    return () => observer.disconnect()
  }, [view])
  return (
    <canvas className="orbit" ref={ref} role="img" aria-label={`采集机位示意图，当前选择${view}`} />
  )
}
