import { useState, useEffect, useCallback } from 'react'
import {
  UserPlus, Users, Shield, User, Trash2,
  CheckCircle, XCircle, Loader2, Eye, EyeOff,
  Pencil, Search, X
} from 'lucide-react'
import { fetchUsers, createUser, updateUser, deleteUser } from '../api/vesselApi'
import { useAuth } from '../context/AuthContext'
import './AdminPage.css'

// ── Helpers ───────────────────────────────────────────────────────────────────
function getInitials(name = '') {
  return name.split(/[\s_-]/).map(w => w[0]).join('').toUpperCase().slice(0, 2) || '?'
}
function formatDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
}

// ── Stat card ─────────────────────────────────────────────────────────────────
function StatCard({ icon, label, value, accent }) {
  return (
    <div className="adm-stat" style={{ '--accent': accent }}>
      <div className="adm-stat-icon">{icon}</div>
      <div className="adm-stat-body">
        <span className="adm-stat-value">{value}</span>
        <span className="adm-stat-label">{label}</span>
      </div>
    </div>
  )
}

// ── Delete confirm modal ──────────────────────────────────────────────────────
function DeleteModal({ user, onConfirm, onCancel, loading }) {
  return (
    <div className="adm-modal-backdrop" onClick={onCancel}>
      <div className="adm-modal" onClick={e => e.stopPropagation()}>
        <div className="adm-modal-icon danger"><Trash2 size={22} /></div>
        <h3 className="adm-modal-title">Delete User</h3>
        <p className="adm-modal-desc">
          Permanently delete <strong>{user?.username}</strong>? This cannot be undone.
        </p>
        <div className="adm-modal-actions">
          <button className="adm-modal-cancel" onClick={onCancel} disabled={loading}>Cancel</button>
          <button className="adm-modal-confirm danger" onClick={onConfirm} disabled={loading}>
            {loading ? <Loader2 size={13} className="adm-spin" /> : <Trash2 size={13} />}
            Delete
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Create / Edit Drawer ──────────────────────────────────────────────────────
function UserDrawer({ editUser, onSaved, onClose }) {
  const isEdit = !!editUser
  const [form, setForm] = useState({
    username: editUser?.username || '',
    email:    editUser?.email    || '',
    password: '',
    role:     editUser?.role     || 'user',
    is_active: editUser?.is_active ?? true,
  })
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState('')
  const [showPass, setShowPass] = useState(false)

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    const { username, email, password, role, is_active } = form

    if (!isEdit) {
      if (!username.trim() || !email.trim() || !password) { setError('All fields are required.'); return }
      if (!/\S+@\S+\.\S+/.test(email))                   { setError('Enter a valid email.'); return }
      if (password.length < 6)                            { setError('Password must be at least 6 characters.'); return }
    } else {
      if (!username.trim() || !email.trim())              { setError('Username and email are required.'); return }
      if (password && password.length < 6)                { setError('New password must be at least 6 characters.'); return }
    }

    setLoading(true)
    try {
      let saved
      if (isEdit) {
        const payload = { role, is_active }
        if (password) payload.password = password
        saved = await updateUser(editUser.id, payload)
      } else {
        saved = await createUser({ username: username.trim(), email: email.trim(), password, role })
      }
      onSaved(saved, isEdit)
      onClose()
    } catch (e) {
      setError(e?.response?.data?.detail || `Failed to ${isEdit ? 'update' : 'create'} user.`)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="adm-drawer-backdrop" onClick={onClose}>
      <div className="adm-drawer" onClick={e => e.stopPropagation()}>

        {/* Header */}
        <div className="adm-drawer-header">
          <div className="adm-drawer-title">
            {isEdit ? <><Pencil size={15} /> Edit User</> : <><UserPlus size={15} /> Create New User</>}
          </div>
          <button className="adm-drawer-close" onClick={onClose}><X size={16} /></button>
        </div>

        <form className="adm-drawer-form" onSubmit={handleSubmit} noValidate>

          {/* Username */}
          <div className="adm-drawer-field">
            <label htmlFor="dr-username">Username</label>
            <input
              id="dr-username"
              type="text"
              placeholder="e.g. john_doe"
              value={form.username}
              onChange={e => set('username', e.target.value)}
              disabled={loading || isEdit}  /* can't rename on edit */
            />
            {isEdit && <span className="adm-drawer-hint">Username cannot be changed</span>}
          </div>

          {/* Email */}
          <div className="adm-drawer-field">
            <label htmlFor="dr-email">Email Address</label>
            <input
              id="dr-email"
              type="email"
              placeholder="e.g. john@company.com"
              value={form.email}
              onChange={e => set('email', e.target.value)}
              disabled={loading || isEdit}  /* can't change email on edit */
            />
          </div>

          {/* Password */}
          <div className="adm-drawer-field">
            <label htmlFor="dr-password">
              {isEdit ? 'New Password (leave blank to keep)' : 'Password'}
            </label>
            <div className="adm-drawer-pass-wrap">
              <input
                id="dr-password"
                type={showPass ? 'text' : 'password'}
                placeholder={isEdit ? 'Leave blank to keep current' : 'Min. 6 characters'}
                value={form.password}
                onChange={e => set('password', e.target.value)}
                disabled={loading}
              />
              <button type="button" className="adm-drawer-eye" onClick={() => setShowPass(v => !v)} tabIndex={-1}>
                {showPass ? <EyeOff size={13} /> : <Eye size={13} />}
              </button>
            </div>
          </div>

          {/* Role */}
          <div className="adm-drawer-field">
            <label>Role</label>
            <div className="adm-role-toggle">
              <button
                type="button"
                className={`adm-role-opt${form.role === 'user' ? ' active user' : ''}`}
                onClick={() => set('role', 'user')}
                disabled={loading}
              >
                <User size={13} /> User
              </button>
              <button
                type="button"
                className={`adm-role-opt${form.role === 'admin' ? ' active admin' : ''}`}
                onClick={() => set('role', 'admin')}
                disabled={loading}
              >
                <Shield size={13} /> Admin
              </button>
            </div>
          </div>

          {/* Active status — only on edit */}
          {isEdit && (
            <div className="adm-drawer-field">
              <label>Account Status</label>
              <div className="adm-role-toggle">
                <button
                  type="button"
                  className={`adm-role-opt${form.is_active ? ' active user' : ''}`}
                  onClick={() => set('is_active', true)}
                  disabled={loading}
                >
                  <CheckCircle size={13} /> Active
                </button>
                <button
                  type="button"
                  className={`adm-role-opt${!form.is_active ? ' active danger' : ''}`}
                  onClick={() => set('is_active', false)}
                  disabled={loading}
                >
                  <XCircle size={13} /> Disabled
                </button>
              </div>
            </div>
          )}

          {error && (
            <div className="adm-drawer-error">
              <XCircle size={13} /> {error}
            </div>
          )}

          <button type="submit" className="adm-drawer-submit" disabled={loading}>
            {loading
              ? <><Loader2 size={13} className="adm-spin" /> {isEdit ? 'Saving…' : 'Creating…'}</>
              : isEdit
                ? <><Pencil size={13} /> Save Changes</>
                : <><UserPlus size={13} /> Create User</>
            }
          </button>

        </form>
      </div>
    </div>
  )
}

// ── Main Component ────────────────────────────────────────────────────────────
export default function AdminPage() {
  const { user: currentUser } = useAuth()

  const [users,        setUsers]        = useState([])
  const [loading,      setLoading]      = useState(true)
  const [error,        setError]        = useState('')
  const [search,       setSearch]       = useState('')
  const [drawerUser,   setDrawerUser]   = useState(null)   // null=closed, false=create, obj=edit
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [deleting,     setDeleting]     = useState(false)

  // ── Load ──────────────────────────────────────────────────────
  const loadUsers = useCallback(async () => {
    setLoading(true); setError('')
    try { setUsers(await fetchUsers()) }
    catch (e) { setError(e?.response?.data?.detail || 'Failed to load users') }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { loadUsers() }, [loadUsers])

  // ── Stats ──────────────────────────────────────────────────────
  const total   = users.length
  const active  = users.filter(u => u.is_active).length
  const admins  = users.filter(u => u.role === 'admin').length
  const regular = users.filter(u => u.role === 'user').length

  // ── Filter ────────────────────────────────────────────────────
  const filtered = users.filter(u =>
    !search ||
    u.username.toLowerCase().includes(search.toLowerCase()) ||
    u.email.toLowerCase().includes(search.toLowerCase())
  )

  // ── Saved (create or edit) ────────────────────────────────────
  function handleSaved(saved, isEdit) {
    if (isEdit) {
      setUsers(prev => prev.map(u => u.id === saved.id ? saved : u))
    } else {
      setUsers(prev => [...prev, saved])
    }
  }

  // ── Delete ────────────────────────────────────────────────────
  async function handleDelete() {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await deleteUser(deleteTarget.id)
      setUsers(prev => prev.filter(u => u.id !== deleteTarget.id))
      setDeleteTarget(null)
    } catch (e) { alert(e?.response?.data?.detail || 'Failed to delete') }
    finally { setDeleting(false) }
  }

  return (
    <div className="adm-root">
      <div className="adm-inner">

        {/* ── Stats ─────────────────────────────────────── */}
        <div className="adm-stats-row">
          <StatCard icon={<Users size={18} />}       label="Total Users"   value={total}   accent="#38bdf8" />
          <StatCard icon={<CheckCircle size={18} />} label="Active"        value={active}  accent="#34d399" />
          <StatCard icon={<Shield size={18} />}      label="Admins"        value={admins}  accent="#a78bfa" />
          <StatCard icon={<User size={18} />}        label="Regular Users" value={regular} accent="#f59e0b" />
        </div>

        {/* ── Toolbar ───────────────────────────────────── */}
        <div className="adm-toolbar">
          <div className="adm-search-wrap">
            <Search size={13} className="adm-search-icon" />
            <input
              className="adm-search"
              type="text"
              placeholder="Search by name or email…"
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
            {search && (
              <button className="adm-search-clear" onClick={() => setSearch('')}>
                <X size={12} />
              </button>
            )}
          </div>
          <button
            id="adm-add-user-btn"
            className="adm-add-btn"
            onClick={() => setDrawerUser(false)}
          >
            <UserPlus size={14} /> Add User
          </button>
        </div>

        {error && <div className="adm-error-bar"><XCircle size={13} /> {error}</div>}

        {/* ── Table ─────────────────────────────────────── */}
        <div className="adm-table-card">
          {loading ? (
            <div className="adm-loading-state">
              <Loader2 size={18} className="adm-spin" />
              <span>Loading users…</span>
            </div>
          ) : (
            <table className="adm-table">
              <thead>
                <tr>
                  <th>User</th>
                  <th>Email</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Joined</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 && (
                  <tr>
                    <td colSpan={6} className="adm-empty">
                      {search ? `No users matching "${search}"` : 'No users found.'}
                    </td>
                  </tr>
                )}
                {filtered.map(u => {
                  const isSelf = u.id === currentUser?.id
                  return (
                    <tr key={u.id} className={isSelf ? 'adm-row-self' : ''}>
                      {/* Avatar + name */}
                      <td>
                        <div className="adm-user-cell">
                          <div className={`adm-avatar ${u.role}`}>{getInitials(u.username)}</div>
                          <span className="adm-user-name">
                            {u.username}
                            {isSelf && <span className="adm-you-badge">you</span>}
                          </span>
                        </div>
                      </td>

                      {/* Email */}
                      <td className="adm-email">{u.email}</td>

                      {/* Role badge */}
                      <td>
                        <span className={`adm-role-badge ${u.role}`}>
                          {u.role === 'admin' ? <Shield size={10} /> : <User size={10} />}
                          {u.role}
                        </span>
                      </td>

                      {/* Status */}
                      <td>
                        <span className={`adm-status-badge ${u.is_active ? 'active' : 'inactive'}`}>
                          <span className="adm-status-dot" />
                          {u.is_active ? 'Active' : 'Disabled'}
                        </span>
                      </td>

                      {/* Date */}
                      <td className="adm-date">{formatDate(u.created_at)}</td>

                      {/* Edit + Delete buttons */}
                      <td>
                        {isSelf
                          ? <span className="adm-self-note">—</span>
                          : (
                            <div className="adm-row-actions">
                              <button
                                className="adm-action-edit"
                                data-tooltip="Edit user"
                                onClick={() => setDrawerUser(u)}
                              >
                                <Pencil size={15} />
                              </button>
                              <button
                                className="adm-action-delete"
                                data-tooltip="Delete user"
                                onClick={() => setDeleteTarget(u)}
                              >
                                <Trash2 size={15} />
                              </button>
                            </div>
                          )
                        }
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>

        {!loading && (
          <div className="adm-footer">
            Showing {filtered.length} of {total} users
          </div>
        )}

      </div>

      {/* Drawer — false = create, object = edit */}
      {drawerUser !== null && (
        <UserDrawer
          editUser={drawerUser || null}
          onSaved={handleSaved}
          onClose={() => setDrawerUser(null)}
        />
      )}

      {/* Delete modal */}
      {deleteTarget && (
        <DeleteModal
          user={deleteTarget}
          onConfirm={handleDelete}
          onCancel={() => setDeleteTarget(null)}
          loading={deleting}
        />
      )}
    </div>
  )
}
