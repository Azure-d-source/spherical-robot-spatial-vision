import { Material, Mesh, Object3D, Points, Texture } from 'three'
import type { BufferGeometry } from 'three'

export function disposeObjects(root: Object3D) {
  const geometries = new Set<BufferGeometry>()
  const materials = new Set<Material>()
  const textures = new Set<Texture>()

  root.traverse((object) => {
    if (!(object instanceof Mesh || object instanceof Points)) return
    geometries.add(object.geometry)
    const values: Material[] = Array.isArray(object.material)
      ? object.material
      : [object.material]
    values.forEach((material) => materials.add(material))
  })
  materials.forEach((material) => {
    Object.values(material).forEach((value: unknown) => {
      if (value instanceof Texture) textures.add(value)
    })
    material.dispose()
  })
  textures.forEach((texture) => {
    const image: unknown = texture.source.data
    if (typeof ImageBitmap !== 'undefined' && image instanceof ImageBitmap)
      image.close()
    texture.dispose()
  })
  geometries.forEach((geometry) => geometry.dispose())
}
