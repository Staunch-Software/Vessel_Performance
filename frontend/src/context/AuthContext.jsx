import { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { loginUser, fetchCurrentUser } from '../api/vesselApi'

// ── Auth Context ──────────────────────────────────────────────────────────────
const AuthContext = createContext(null)

const TOKEN_KEY = 'vp_auth_token'
const USER_KEY  = 'vp_auth_user'

export function AuthProvider({ children }) {
  const [user,  setUser]  = useState(() => {
    try { return JSON.parse(localStorage.getItem(USER_KEY)) } catch { return null }
  })
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY) || null)
  const [loading, setLoading] = useState(true)   // true during initial token validation

  // Validate token on mount — if expired or invalid, clear session
  useEffect(() => {
    if (!token) { setLoading(false); return }
    fetchCurrentUser()
      .then(userData => {
        setUser(userData)
        localStorage.setItem(USER_KEY, JSON.stringify(userData))
      })
      .catch(() => {
        // Token invalid or expired — clear everything
        localStorage.removeItem(TOKEN_KEY)
        localStorage.removeItem(USER_KEY)
        setToken(null)
        setUser(null)
      })
      .finally(() => setLoading(false))
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const login = useCallback(async (username, password) => {
    const data = await loginUser(username, password)
    // Persist token so the interceptor can pick it up immediately
    localStorage.setItem(TOKEN_KEY, data.access_token)
    setToken(data.access_token)
    // Fetch full profile after login
    const profile = await fetchCurrentUser()
    localStorage.setItem(USER_KEY, JSON.stringify(profile))
    setUser(profile)
    return profile
  }, [])

  const logout = useCallback(() => {
    // Remove all local storage keys associated with the application state
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const key = localStorage.key(i)
      if (key && key.startsWith('vp_')) {
        localStorage.removeItem(key)
      }
    }
    setToken(null)
    setUser(null)
  }, [])

  const isAuthenticated = !!token && !!user
  const isAdmin = user?.role === 'admin'

  return (
    <AuthContext.Provider value={{ user, token, login, logout, isAuthenticated, isAdmin, loading }}>
      {children}
    </AuthContext.Provider>
  )
}

// ── Hook ─────────────────────────────────────────────────────────────────────
export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
