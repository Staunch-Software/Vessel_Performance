import { Clock } from 'lucide-react'
import './EmissionPage.css'

// Shared placeholder for the 4 not-yet-built regime pages (EU MRV, EU ETS,
// FuelEU Maritime, Biofuel Calc) — same "definition pending" convention
// already used for ESG/SCC/ESI on the old Emission page, so nothing here
// fabricates data ahead of the real build.
export default function EmissionComingSoonPage({ title, note }) {
  return (
    <div className="em-page">
      <div className="em-topbar">
        <span className="em-title">{title}</span>
      </div>
      <div className="em-body">
        <div className="em-card">
          <div className="em-card-title"><Clock size={13} /> {title}</div>
          <div className="em-empty">{note || 'Not built yet — coming in a later phase.'}</div>
        </div>
      </div>
    </div>
  )
}
