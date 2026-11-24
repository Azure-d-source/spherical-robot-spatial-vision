import { useEffect, useRef, useState } from 'react'

export default function SuperSplatFrame({ urls }: { urls: string[] }) {
  const iframe = useRef<HTMLIFrameElement>(null)
  const [attempt, setAttempt] = useState(0)
  const [status, setStatus] = useState<'loading' | 'ready'>('loading')
  const url = urls[Math.floor(attempt / 2)]
  const webgl = attempt % 2 === 1
  const src = url
    ? '/supersplat/index.html?content=' +
      encodeURIComponent(url) +
      (webgl ? '&webgl' : '')
    : ''

  useEffect(() => {
    if (!src) return
    const child = iframe.current?.contentWindow
    function fallback() {
      setStatus('loading')
      setAttempt((value) => value + 1)
    }
    const timeout = window.setTimeout(fallback, 45000)
    function onMessage(event: MessageEvent) {
      if (
        event.origin !== location.origin ||
        event.source !== child ||
        event.data?.type !== 'orbitforge:splat'
      )
        return
      if (event.data.status === 'ready') {
        window.clearTimeout(timeout)
        setStatus('ready')
      } else if (event.data.status === 'error') {
        window.clearTimeout(timeout)
        fallback()
      }
    }
    window.addEventListener('message', onMessage)
    return () => {
      window.clearTimeout(timeout)
      window.removeEventListener('message', onMessage)
      queueMicrotask(() => {
        if (iframe.current?.contentWindow !== child) {
          child?.postMessage(
            { type: 'orbitforge:dispose-splat' },
            location.origin,
          )
        }
      })
    }
  }, [src])

  return (
    <>
      <div className="viewer-graphics">
        {src && (
          <iframe
            key={src}
            ref={iframe}
            title="SuperSplat 3DGS 查看器"
            src={src}
            allowFullScreen
          />
        )}
        {(!src || status === 'loading') && (
          <div className="viewer-overlay" role={src ? 'status' : 'alert'}>
            {src
              ? '正在打开 3DGS…'
              : '3DGS 无法打开，请检查产物和浏览器图形支持。'}
          </div>
        )}
      </div>
      {status === 'ready' && src && (
        <p className="viewer-message hint">
          已加载 {url.endsWith('.sog') ? 'SOG' : 'PLY'} · 拖动环绕查看
        </p>
      )}
    </>
  )
}
