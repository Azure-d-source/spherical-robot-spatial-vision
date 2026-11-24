export const initialLayout = { x: 0, z: 0, rotation: 0 }
export type SimulationLayout = typeof initialLayout

export function layoutKey({ x, z, rotation }: SimulationLayout) {
  return `sim-v1:${Math.round(x * 100)},${Math.round(z * 100)},${rotation === -180 ? 180 : rotation}`
}

export function frameLayout(label: string) {
  return /^\[(sim-v1:-?\d+,-?\d+,-?\d+)\] /.exec(label)?.[1]
}

export function layoutTitle(key: string) {
  if (!key) return '普通采集'
  if (key === layoutKey(initialLayout)) return '布局 A · 初始位姿'
  const [x, z, rotation] = key.slice('sim-v1:'.length).split(',')
  return `布局 X ${Number(x) / 100} / Z ${Number(z) / 100} · ${rotation}°`
}

export function frameLabel(label: string) {
  const layout = frameLayout(label)
  return layout ? label.slice(layout.length + 3).replace(/ @cam:-?\d+,\d+,\d+$/, '') : label
}
