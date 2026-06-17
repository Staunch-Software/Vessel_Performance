import { useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import './SideNav.css'

const NAV_ITEMS = [
  { path: '/',              icon: '📋', label: 'Logbook+'       },
  { path: '/vessel-report', icon: '🚢', label: 'Vessel Report'  },
]

export default function SideNav() {
  const [collapsed, setCollapsed] = useState(false)
  const navigate  = useNavigate()
  const location  = useLocation()

  return (
    <aside className={`sidenav${collapsed ? ' collapsed' : ''}`}>
      <div className="sidenav-logo">
        <div className="sidenav-logo-icon">VP</div>
        {!collapsed && (
          <div className="sidenav-logo-text">
            <span className="sidenav-logo-title">Vessel Perf.</span>
            <span className="sidenav-logo-sub">Powered by Analytics</span>
          </div>
        )}
        <button
          className="sidenav-toggle"
          onClick={() => setCollapsed(c => !c)}
          title={collapsed ? 'Expand' : 'Collapse'}
          style={{ marginLeft: 'auto' }}
        >
          {collapsed ? '›' : '‹'}
        </button>
      </div>

      <nav className="sidenav-nav">
        {NAV_ITEMS.map(item => (
          <div
            key={item.path}
            className={`sidenav-item${location.pathname === item.path ? ' active' : ''}`}
            onClick={() => navigate(item.path)}
            title={collapsed ? item.label : ''}
          >
            <span className="sidenav-icon">{item.icon}</span>
            {!collapsed && <span className="sidenav-label">{item.label}</span>}
          </div>
        ))}
      </nav>

      {!collapsed && (
        <div className="sidenav-footer">technical@ozellar.com</div>
      )}
    </aside>
  )
}
