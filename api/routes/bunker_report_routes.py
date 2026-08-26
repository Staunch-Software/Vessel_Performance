"""
MariApps Bunker Report API — serves the mariapps_bunker_reports table (scraped
by backend/mariapps_pipeline/bunker_report_scraper.py) and generates short-lived
SAS download links for each record's attached Bunker Delivery Note PDF.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import inspect as sa_inspect

from backend.database import SessionLocal
from backend.models import MariAppsBunkerReport, Vessel
from backend.mariapps_pipeline.blob_storage import get_download_url

log = logging.getLogger(__name__)
router = APIRouter(prefix="/bunker-report", tags=["bunker-report"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _row_dict(row):
    mapper = sa_inspect(type(row))
    return {c.key: getattr(row, c.key) for c in mapper.attrs}


@router.get("/vessels")
def list_bunker_vessels(db: Session = Depends(get_db)):
    """Vessels that actually have at least one bunker report row — lets the
    frontend only offer vessels with real data rather than all 14."""
    imos = [r[0] for r in db.query(MariAppsBunkerReport.vessel_imo).distinct().all()]
    if not imos:
        return []
    vessels = db.query(Vessel).filter(Vessel.imo_number.in_(imos)).order_by(Vessel.vessel_name).all()
    return [{"imo_number": v.imo_number, "vessel_name": v.vessel_name} for v in vessels]


@router.get("/{imo}")
def get_bunker_reports(
    imo: str,
    from_date: Optional[str] = Query(None, description="YYYY-MM-DD, filters on Begin of Bunkering"),
    to_date: Optional[str] = Query(None, description="YYYY-MM-DD, filters on Begin of Bunkering"),
    db: Session = Depends(get_db),
):
    q = db.query(MariAppsBunkerReport).filter(MariAppsBunkerReport.vessel_imo == imo)
    # Order by id (insertion order) — the scraper saves rows in the exact order it
    # read them from the MariApps grid (row 0, row 1, ...), so this preserves the
    # same row order MariApps itself shows rather than re-sorting by a display
    # string (begin_of_bunkering isn't a real date column and doesn't even sort
    # chronologically as a string — "01-Mar-2026" vs "22-Aug-2026" sorts wrong).
    q = q.order_by(MariAppsBunkerReport.id.asc())
    rows = q.all()

    out = []
    for r in rows:
        d = _row_dict(r)
        # download_url mirrors attachments[0] for simple single-attachment reads —
        # attachments[] carries a download_url per file for transactions with more
        # than one (BDN + Note of Protest + LOP, etc.).
        d["download_url"] = get_download_url(r.blob_path) if r.blob_path else None
        d["attachments"] = [
            {**a, "download_url": get_download_url(a["blob_path"]) if a.get("blob_path") else None}
            for a in (r.attachments or [])
        ]
        # raw_json is the full scraped row dict — useful for debugging, not for the UI table.
        d.pop("raw_json", None)
        out.append(d)
    return out
