import { useEffect, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { api, ApiError, errorText, sessionExpired } from './api'
import type { Account } from './api'

type Session =
  | { stage: 'checking' }
  | { stage: 'unavailable'; message: string }
  | { stage: 'signed-out'; expired?: boolean }
  | { stage: 'ready'; account?: Account }

export function WorkbenchBrand() {
  return (
    <>
      <div className="brand">
        <span className="brand-mark" aria-hidden="true"><i /></span>
        <strong>绕物成景</strong>
      </div>
      <span className="brand-sub">空间视觉工作台</span>
    </>
  )
}

function LoginForm({ onLogin }: { onLogin: (account: Account) => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (busy || !email.trim() || !password) return
    setBusy(true)
    setError('')
    try {
      onLogin(await api.login(email.trim(), password))
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="form-body" onSubmit={submit}>
      <label>
        邮箱
        <input autoComplete="username" type="email" required maxLength={254} value={email}
          onChange={(event) => setEmail(event.target.value)} disabled={busy} />
      </label>
      <label>
        密码
        <input autoComplete="current-password" type="password" required maxLength={256} value={password}
          onChange={(event) => setPassword(event.target.value)} disabled={busy} />
      </label>
      {error && <p className="error" role="alert">{error}</p>}
      <button className="primary" disabled={busy}>{busy ? '正在登录…' : '登录'}</button>
    </form>
  )
}

export function SessionGate({ children }: {
  children: (account?: Account, logout?: () => Promise<void>) => ReactNode
}) {
  const [session, setSession] = useState<Session>({ stage: 'checking' })
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    const { signal } = controller
    setSession({ stage: 'checking' })

    async function check() {
      try {
        const health = await api.health(signal)
        if (signal.aborted) return
        if (health.status !== 'ok') throw new Error('工作台暂时无法连接后端。')
        const account = health.workbench === 'team' ? await api.me(signal) : undefined
        if (!signal.aborted) setSession({ stage: 'ready', account })
      } catch (err) {
        if (signal.aborted) return
        if (err instanceof ApiError && err.code === 'LOGIN_REQUIRED') {
          setSession({ stage: 'signed-out' })
        } else {
          setSession({ stage: 'unavailable', message: errorText(err) })
        }
      }
    }

    void check()
    return () => controller.abort()
  }, [retry])

  useEffect(() => {
    function expire() {
      setSession((current) => current.stage === 'ready' && current.account
        ? { stage: 'signed-out', expired: true }
        : current)
    }
    window.addEventListener(sessionExpired, expire)
    return () => window.removeEventListener(sessionExpired, expire)
  }, [])

  async function logout() {
    await api.logout()
    setSession({ stage: 'signed-out' })
  }

  if (session.stage === 'ready') {
    return children(session.account, session.account ? logout : undefined)
  }

  return (
    <div className="session-shell">
      <header className="topbar"><WorkbenchBrand /></header>
      <main className="session-main">
        <section className="card session-card">
          <div className="card-heading">
            <h1>{session.stage === 'signed-out' ? '登录工作台' : '空间视觉工作台'}</h1>
          </div>
          {session.stage === 'checking' && <p className="form-body" role="status">正在连接工作台…</p>}
          {session.stage === 'unavailable' && (
            <div className="form-body">
              <p className="error" role="alert">{session.message}</p>
              <button className="secondary" onClick={() => setRetry((value) => value + 1)}>重试连接</button>
            </div>
          )}
          {session.stage === 'signed-out' && (
            <>
              {session.expired && <p className="session-hint" role="status">登录已过期，请重新登录。</p>}
              <LoginForm onLogin={(account) => setSession({ stage: 'ready', account })} />
            </>
          )}
        </section>
      </main>
    </div>
  )
}
