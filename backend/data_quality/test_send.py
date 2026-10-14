# ===========================================================================
# backend/data_quality/test_send.py
#
# Manual template preview — before sending real Data Quality digest mails to
# actual vessel recipients (client request 2026-10), this runs the SAME
# detection logic against REAL data and sends every vessel's digest to a
# single test address instead. Entirely read-only: unlike daily_job.py, this
# never writes to DataQualityFinding (no open/resolved/notify_count changes),
# so it's safe to re-run as many times as needed while reviewing the
# template — it won't throw off the real job's reminder tracking later.
#
# Checks ONE date (default: yesterday) across all vessels — pass a specific
# YYYY-MM-DD as the 2nd argument to preview a day you already know has real
# gaps, rather than hoping yesterday happens to have one.
#
# Run from repo root:
#   python -m backend.data_quality.test_send
#   python -m backend.data_quality.test_send techdevops@ozellar.com
#   python -m backend.data_quality.test_send techdevops@ozellar.com 2026-09-29
# ===========================================================================
import logging
import sys
from datetime import date, datetime, timedelta

from ..database import SessionLocal
from ..models import Vessel
from ..reporting.email_service import send_email
from .checks import run_checks_for_date
from .daily_job import build_digest_html

log = logging.getLogger(__name__)

DEFAULT_TEST_RECIPIENT = "techdevops@ozellar.com"


def run_test_send(test_recipient=DEFAULT_TEST_RECIPIENT, check_date=None):
    check_date = check_date or (date.today() - timedelta(days=1))
    db = SessionLocal()
    try:
        vessels = (
            db.query(Vessel)
            .filter((Vessel.wni_enabled.is_(True)) | (Vessel.mari_enabled.is_(True)))
            .all()
        )

        sent = checked = 0
        for vessel in vessels:
            checked += 1
            findings = run_checks_for_date(db, vessel.imo_number, check_date)
            if not findings:
                continue

            entries = [
                {"source_id": source, "rule_key": rule_key, "report_date": check_date, "detail": detail, "notify_count": 0}
                for (source, rule_key), detail in findings.items()
            ]
            html = build_digest_html(vessel.vessel_name, entries)
            ok = send_email(
                subject=f"[TEST] [Data Quality] {vessel.vessel_name} — missing mandatory data ({check_date})",
                html_content=html,
                recipients=[test_recipient],
                cc_recipients=None,
            )
            if ok:
                sent += 1
                log.info(f"Test digest sent for {vessel.vessel_name} ({check_date}) -> {test_recipient}")
            else:
                log.error(f"Test digest FAILED to send for {vessel.vessel_name} ({check_date})")

        log.info(
            f"Test send complete for {check_date} — {checked} vessels checked, "
            f"{sent} digest(s) sent to {test_recipient}. No DataQualityFinding rows were written."
        )
        if sent == 0:
            log.info(f"No vessel had a gap on {check_date} — pass a different YYYY-MM-DD as the 3rd argument to try a known-bad day.")
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
    recipient = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TEST_RECIPIENT
    cdate = datetime.strptime(sys.argv[2], "%Y-%m-%d").date() if len(sys.argv) > 2 else None
    run_test_send(recipient, cdate)
