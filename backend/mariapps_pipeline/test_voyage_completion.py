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
# ===========================================================================
import logging
import sys

from ..database import SessionLocal
from ..models import AnalysisData, RawMariAppsLog, Vessel
from .voyage_completion_mail import maybe_send_voyage_completion_mail

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
log = logging.getLogger(__name__)

DEFAULT_TO = "techdevops@ozellar.com"


def run(to_addr, vessel_name=None):
    db = SessionLocal()
    try:
        q = (
            db.query(RawMariAppsLog, Vessel)
            .join(Vessel, Vessel.imo_number == RawMariAppsLog.vessel_imo)
            .filter(RawMariAppsLog.log_type.ilike("%EOSP%"))
        )
        q = q.filter(Vessel.vessel_name == vessel_name) if vessel_name else q.filter(Vessel.vessel_name.ilike("AMNS%"))
        row = q.order_by(RawMariAppsLog.log_date.desc()).first()
        if not row:
            log.error("No ingested MariApps EOSP log found for that vessel.")
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
    run(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TO, sys.argv[2] if len(sys.argv) > 2 else None)
