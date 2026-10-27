import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.jsx'
import { generateVoyagePdf } from './utils/voyagePdfExport'

// Headless render hook for the voyage-completion mail (backend/mariapps_pipeline/
// voyage_report_pdf.py loads `/?pdf_render=1` in Playwright and calls this).
// Gated by the query param so it is not exposed on a normal page load.
if (new URLSearchParams(window.location.search).get('pdf_render') === '1') {
  window.__vpGenerateVoyagePdf = (args) => generateVoyagePdf({ ...args, returnData: true })
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
)
