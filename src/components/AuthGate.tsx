import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import type { Session } from '@supabase/supabase-js'
import { supabase } from '../lib/supabaseClient'
import '../styles/converter.css'
import '../styles/converter-library-theme.css'

function LoginForm() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    const { error: signInError } = await supabase.auth.signInWithPassword({
      email,
      password,
    })
    setSubmitting(false)
    if (signInError) setError(signInError.message)
  }

  return (
    <div className="converter-app">
      <div className="login-screen">
        <div className="login-brand">
          <img src="/vlrc_logo.png" alt="Victorian Law Reform Commission" />
          <span className="converter-product">
            <strong>Konverter</strong>
            <small>Accessible publishing workspace</small>
          </span>
        </div>
        <div className="panel login-panel">
          <div className="panel-pad">
            <span className="eyebrow">Reviewer console</span>
            <h1 className="login-title">Sign in to continue</h1>
            <p className="lead">Use your Konverter account to convert, review and export accessible reports.</p>
            <form onSubmit={handleSubmit} className="login-form" noValidate>
              <label className="login-field">
                <span className="login-field-label">Email</span>
                <input
                  className="input"
                  type="email"
                  required
                  autoComplete="username"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                />
              </label>
              <label className="login-field">
                <span className="login-field-label">Password</span>
                <input
                  className="input"
                  type="password"
                  required
                  autoComplete="current-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                />
              </label>
              {error ? (
                <div className="banner banner-err" role="alert">
                  <span>{error}</span>
                </div>
              ) : null}
              <button type="submit" className="btn btn-primary btn-block btn-lg" disabled={submitting}>
                {submitting ? 'Signing in…' : 'Sign in'}
              </button>
            </form>
          </div>
        </div>
      </div>
    </div>
  )
}

export default function AuthGate({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session)
      setLoading(false)
    })
    const { data: subscription } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession)
    })
    return () => subscription.subscription.unsubscribe()
  }, [])

  if (loading) {
    return (
      <div className="converter-app">
        <div className="page-loading" role="status">Loading…</div>
      </div>
    )
  }

  if (!session) {
    return <LoginForm />
  }

  return <>{children}</>
}
