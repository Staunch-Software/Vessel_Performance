"""
sync_routes.py
--------------
Read-only data-sync status for the Vessel Reports page.

  GET /sync/status                  - per-vessel sync status for both sources
  GET /sync/status?vessel_imo=...   - same, filtered to one vessel

"Last synced" is derived from the raw staging tables' ingestion timestamps
(raw_noon_reports.downloaded_at for WNI, raw_mariapps_logs.extracted_at for
MariApps). "Latest report" + staleness come from analysis_data.Date.

NOTE: this endpoint does NOT trigger any ingestion — it only reports state.
On-demand "Sync now" is a separate, later feature.
"""

from datetime import date, datetime
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.models import Vessel, RawNoonReport, RawMariAppsLog, AnalysisData

router = APIRouter(prefix="/sync")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _iso_dt(dt):
    return dt.isoformat() if dt else None


def _iso_d(d):
    return d.isoformat() if d else None


@router.get("/status")
def sync_status(vessel_imo: str = Query(None), db: Session = Depends(get_db)):
    """Return last-sync / latest-report / counts per vessel for WNI and MariApps."""
    try:
        today = date.today()

        # ── Raw-staging ingestion timestamps (per vessel) ──
        wni_q = db.query(
            RawNoonReport.vessel_imo,
            func.max(RawNoonReport.downloaded_at),
            func.count(),
        )
        mari_q = db.query(
            RawMariAppsLog.vessel_imo,
            func.max(RawMariAppsLog.extracted_at),
            func.count(),
        )
        # ── Latest report date + row counts from analysis_data (per vessel + source) ──
        an_q = db.query(
            AnalysisData.vessel_imo,
            AnalysisData.source_id,
            func.max(AnalysisData.Date),
            func.count(),
        )

        if vessel_imo:
            wni_q  = wni_q.filter(RawNoonReport.vessel_imo == vessel_imo)
            mari_q = mari_q.filter(RawMariAppsLog.vessel_imo == vessel_imo)
            an_q   = an_q.filter(AnalysisData.vessel_imo == vessel_imo)

        wni_raw  = {r[0]: (r[1], r[2]) for r in wni_q.group_by(RawNoonReport.vessel_imo).all()}
        mari_raw = {r[0]: (r[1], r[2]) for r in mari_q.group_by(RawMariAppsLog.vessel_imo).all()}

        an = {}
        for imo, sid, max_date, cnt in an_q.group_by(
            AnalysisData.vessel_imo, AnalysisData.source_id
        ).all():
            an.setdefault(imo, {})[sid] = (max_date, cnt)

        # ── Vessel list ──
        v_query = db.query(Vessel).order_by(Vessel.vessel_name)
        if vessel_imo:
            v_query = v_query.filter(Vessel.imo_number == vessel_imo)
        vessels = v_query.all()

        def stale_days(d):
            return (today - d).days if d else None

        def source_block(raw_entry, an_entry):
            last_synced = raw_entry[0] if raw_entry else None
            raw_count   = raw_entry[1] if raw_entry else 0
            latest_date = an_entry[0] if an_entry else None
            an_count    = an_entry[1] if an_entry else 0
            return {
                "last_synced":        _iso_dt(last_synced),
                "raw_count":          raw_count,
                "latest_report_date": _iso_d(latest_date),
                "analysis_count":     an_count,
                "stale_days":         stale_days(latest_date),
            }

        out = []
        for v in vessels:
            imo = str(v.imo_number)
            v_an = an.get(imo, {})
            out.append({
                "imo_number":  imo,
                "vessel_name": v.vessel_name,
                "wni":         source_block(wni_raw.get(imo),  v_an.get("wni")),
                "mari_apps":   source_block(mari_raw.get(imo), v_an.get("mari_apps")),
            })

        return {
            "generated_at": datetime.utcnow().isoformat(),
            "vessels": out,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sync status error: {e}")
