# ===========================================================================
# Manual preview of the voyage-completion mail — uses the REAL code path
# (PDF render + mail build) for the most recent already-ingested MariApps EOSP
# of a vessel, but sends ONLY to the given test address. The stored
# voyage_completion recipient rows (TO and CC) are never read or used.
# Writes nothing to the DB.
#
# Needs the built frontend reachable at VOYAGE_PDF_FRONTEND_URL (see
# voyage_report_pdf.py) and the backend API behind it.
#
# Run from repo root:
#   python -m backend.mariapps_pipeline.test_voyage_completion techdevops@ozellar.com
#   python -m backend.mariapps_pipeline.test_voyage_completion techdevops@ozellar.com "AMNS POLAR"
#   python -m backend.mariapps_pipeline.test_voyage_completion techdevops@ozellar.com "AMNSI MAXIMUS" "60B/01"
# ===========================================================================
import logging
import sys

from ..database import SessionLocal
from ..models import AnalysisData, RawMariAppsLog, Vessel
from .voyage_completion_mail import maybe_send_voyage_completion_mail, voyage_data_summary

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
log = logging.getLogger(__name__)

DEFAULT_TO = "techdevops@ozellar.com"


def run(to_addr, vessel_name=None, voyage_no=None):
    db = SessionLocal()
    try:
        q = (
            db.query(RawMariAppsLog, Vessel)
            .join(Vessel, Vessel.imo_number == RawMariAppsLog.vessel_imo)
            .filter(RawMariAppsLog.log_type.ilike("%EOSP%"))
        )
        q = q.filter(Vessel.vessel_name == vessel_name) if vessel_name else q.filter(Vessel.vessel_name.ilike("AMNS%"))
        if voyage_no:
            q = q.filter(RawMariAppsLog.leg_number == voyage_no)
        # Latest EOSP whose voyage has enough data to be worth a report (same
        # rule as the real mail), skipping short port shifts.
        row = None
        for cand in q.order_by(RawMariAppsLog.log_date.desc()).limit(200):
            dist, dur, ok = voyage_data_summary(cand[0].vessel_imo, cand[0].leg_number)
            if ok:
                row = cand
                log.info(f"Voyage {cand[0].leg_number}: sea passage {dist:.0f} nm / {dur:.1f} h")
                break
        if not row:
            log.error("No EOSP found whose voyage meets the minimum data threshold.")
            return
        raw, vessel = row
        ad = db.query(AnalysisData).filter_by(raw_mariapps_id=raw.id).first()
        log.info(f"Using {vessel.vessel_name} log {raw.log_number} ({raw.log_date}), voyage {raw.leg_number} -> {to_addr} only")
        ok = maybe_send_voyage_completion_mail(
            db, vessel.imo_number, vessel.vessel_name, raw.log_number, raw.leg_number, raw.log_date,
            from_port=ad.From_Port if ad else None, test_to=to_addr,
        )
        log.info("Sent." if ok else "Send FAILED — see log above.")
    finally:
        db.close()


if __name__ == "__main__":
    run(
        sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TO,
        sys.argv[2] if len(sys.argv) > 2 else None,
        sys.argv[3] if len(sys.argv) > 3 else None,
    )
