import { useState, useRef, useEffect } from 'react'
import { User, Lock, Eye, EyeOff, AlertCircle } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import './LoginPage.css'

export default function LoginPage() {
  const { login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error,    setError]    = useState('')
  const [loading,  setLoading]  = useState(false)
  const [showPass, setShowPass] = useState(false)

  const usernameRef = useRef(null)
  useEffect(() => { usernameRef.current?.focus() }, [])

  async function handleSubmit(e) {
    e.preventDefault()
    if (!username.trim() || !password) {
      setError('Please enter your username and password.')
      return
    }
    setError('')
    setLoading(true)
    try {
      await login(username.trim(), password)
    } catch (err) {
      const msg = err?.response?.data?.detail || 'Incorrect username or password.'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="lp-root">

      {/* ── LEFT — full-bleed image ──────────────────────────── */}
      <div className="lp-left">
        {/* The image itself fills the entire left column */}
        <img src="/login-bg-v4.png" className="lp-bg-img" alt="" />

        {/* Gradient overlay so text is readable at the bottom */}
        <div className="lp-overlay" />

        {/* Content anchored to bottom */}
        <div className="lp-left-content">
          <div className="lp-brand-mark">VP</div>
          <h1 className="lp-brand-name">Vessel Performance</h1>
          <p className="lp-brand-tagline">Maritime Analytics Platform</p>

          <div className="lp-stats-row">
            <div className="lp-stat">
              <span className="lp-stat-val">MariApps</span>
              <span className="lp-stat-lbl">Data Source</span>
            </div>
            <div className="lp-stat-sep" />
            <div className="lp-stat">
              <span className="lp-stat-val">WNI</span>
              <span className="lp-stat-lbl">Weather</span>
            </div>
            <div className="lp-stat-sep" />
            <div className="lp-stat">
              <span className="lp-stat-val">ISO 19030</span>
              <span className="lp-stat-lbl">Standard</span>
            </div>
          </div>
        </div>
      </div>

      {/* ── RIGHT — sign-in form ─────────────────────────────── */}
      <div className="lp-right">
        <div className="lp-form-wrap">

          <div className="lp-form-header">
            <h2 className="lp-form-title">Welcome back</h2>
            <p className="lp-form-sub">Sign in to your account to continue</p>
          </div>

          <form className="lp-form" onSubmit={handleSubmit} noValidate>

            <div className="lp-field">
              <label className="lp-label" htmlFor="lp-username">Username or Email</label>
              <div className="lp-input-row">
                <User size={14} className="lp-input-icon" />
                <input
                  id="lp-username"
                  className="lp-input"
                  type="text"
                  autoComplete="username"
                  placeholder="Enter username or email"
                  value={username}
                  onChange={e => setUsername(e.target.value)}
                  ref={usernameRef}
                  disabled={loading}
                />
              </div>
            </div>

            <div className="lp-field">
              <label className="lp-label" htmlFor="lp-password">Password</label>
              <div className="lp-input-row">
                <Lock size={14} className="lp-input-icon" />
                <input
                  id="lp-password"
                  className="lp-input"
                  type={showPass ? 'text' : 'password'}
                  autoComplete="current-password"
                  placeholder="Enter your password"
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  disabled={loading}
                />
                <button
                  type="button"
                  className="lp-toggle"
                  onClick={() => setShowPass(v => !v)}
                  tabIndex={-1}
                >
                  {showPass ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
            </div>

            {error && (
              <div className="lp-error" role="alert">
                <AlertCircle size={13} />
                <span>{error}</span>
              </div>
            )}

            <button id="lp-submit" type="submit" className="lp-btn" disabled={loading}>
              {loading
                ? <><span className="lp-spinner" /> Signing in…</>
                : 'Sign In'
              }
            </button>

          </form>

          <p className="lp-footer-note">Sessions expire after 8 hours</p>
        </div>
      </div>
    </div>
  )
}
