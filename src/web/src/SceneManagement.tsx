import { useState } from 'react'
import type { FormEvent } from 'react'
import { api, errorText } from './api'
import type { Scene } from './api'

export function SceneManagement({ scene, onChange }: {
  scene: Scene
  onChange: (scene: Scene) => void
}) {
  const [title, setTitle] = useState(scene.title)
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const archived = scene.status === 'archived'

  async function save(change: () => Promise<Scene>) {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      const updated = await change()
      onChange(updated)
      setEditing(false)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  function rename(event: FormEvent) {
    event.preventDefault()
    if (title.trim()) void save(() => api.rename(scene.scene_id, title.trim()))
  }

  return (
    <div className="scene-management">
      {editing && !archived ? (
        <form className="scene-actions" onSubmit={rename}>
          <input aria-label="新场景名称" value={title} maxLength={120} required disabled={busy}
            onChange={(event) => setTitle(event.target.value)} />
          <button className="secondary" disabled={busy || !title.trim()}>保存名称</button>
          <button type="button" className="text-button" disabled={busy} onClick={() => setEditing(false)}>取消</button>
        </form>
      ) : (
        <div className="scene-actions">
          {!archived && (
            <button className="secondary" disabled={busy} onClick={() => {
              setTitle(scene.title)
              setError('')
              setEditing(true)
            }}>改名</button>
          )}
          <button className="secondary" disabled={busy} onClick={() => void save(
            () => archived ? api.restore(scene.scene_id) : api.archive(scene.scene_id),
          )}>
            {archived ? '恢复场景' : '归档场景'}
          </button>
        </div>
      )}
      {error && <p className="error" role="alert">{error}</p>}
    </div>
  )
}
