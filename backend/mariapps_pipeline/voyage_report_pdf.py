"""
Headless render of the Voyage Audit Report PDF for the voyage-completion mail.

The report is built client-side (frontend/src/utils/voyagePdfExport.js — jsPDF
+ html2canvas charts). Rather than re-implementing a ~30-page report in
Python and letting the two drift apart, this loads the built frontend in
headless Chromium (`/?pdf_render=1`, which exposes window.__vpGenerateVoyagePdf
— see frontend/src/main.jsx) and asks it to generate the exact same PDF the
Logbook+ download button produces.

Runs in a SUBPROCESS (render_voyage_pdf -> `python -m ...voyage_report_pdf`)
because save_log() is called from inside the MariApps scraper's own running
Playwright sync session, and Playwright's sync API cannot be nested.

Config: VOYAGE_PDF_FRONTEND_URL — where the built frontend is reachable from
the server (default http://localhost, i.e. nginx on the VM; use
http://localhost:5173 against `npm run dev` locally).
"""
import argparse
import base64
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

FRONTEND_URL = os.getenv("VOYAGE_PDF_FRONTEND_URL", "http://localhost")
RENDER_TIMEOUT_S = 240


def render_voyage_pdf(vessel_imo, vessel_name, voyage_no, source="mari_apps"):
    """Returns the path of the generated PDF, or None on any failure."""
    out_dir = tempfile.mkdtemp(prefix="voyage_report_")
    cmd = [
        sys.executable, "-m", "backend.mariapps_pipeline.voyage_report_pdf",
        "--imo", str(vessel_imo), "--name", str(vessel_name or ""),
        "--voyage", str(voyage_no), "--source", source, "--out-dir", out_dir,
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=RENDER_TIMEOUT_S + 30,
            cwd=str(Path(__file__).resolve().parents[2]),
        )
    except subprocess.TimeoutExpired:
        log.error(f"Voyage PDF render timed out for {vessel_name} {voyage_no}")
        return None
    if proc.returncode != 0:
        log.error(f"Voyage PDF render failed for {vessel_name} {voyage_no}: {proc.stderr[-800:]}")
        return None
    path = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    return path if path and os.path.exists(path) else None


def _render(imo, name, voyage_no, source, out_dir):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            page.set_default_timeout(RENDER_TIMEOUT_S * 1000)
            page.goto(f"{FRONTEND_URL.rstrip('/')}/?pdf_render=1", wait_until="networkidle")
            page.wait_for_function("typeof window.__vpGenerateVoyagePdf === 'function'")
            result = page.evaluate(
                "args => window.__vpGenerateVoyagePdf(args)",
                {
                    "vesselImo": imo, "vesselName": name,
                    "voyageNo": voyage_no, "voyageNos": [voyage_no],
                    "source": source, "loadingCond": "all",
                },
            )
        finally:
            browser.close()

    if result.get("dataWarning"):
        log.warning(f"Voyage PDF generated with a data warning: {result['dataWarning']}")
    path = Path(out_dir) / result["filename"]
    path.write_bytes(base64.b64decode(result["base64"]))
    return str(path)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--imo", required=True)
    ap.add_argument("--name", default="")
    ap.add_argument("--voyage", required=True)
    ap.add_argument("--source", default="mari_apps")
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args()
    print(_render(a.imo, a.name, a.voyage, a.source, a.out_dir))
