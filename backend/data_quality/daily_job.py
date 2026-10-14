# ===========================================================================
# backend/data_quality/daily_job.py
#
# Daily data-quality check + notification job (client request 2026-10,
# Phase 3). Runs once a day, meant to be invoked right after that day's WNI +
# MariApps scrapes have landed (see scripts/run_data_quality_check.sh).
#
# Lifecycle per vessel:
#   1. Re-check yesterday's date for brand-new gaps.
#   2. Re-check every date that still has an OPEN finding from a previous
#      run too — a vessel can correct an older report days later, so an old
#      finding needs to keep being re-verified, not just created once and
#      forgotten.
#   3. Anything still missing -> upsert as 'open' (bumps notify_count next
#      time it's mailed). Anything previously open but NOT found missing
#      this pass -> flip to 'resolved', silently (no "fixed" confirmation
#      mail — client only asked for an alert while something is wrong).
#   4. One digest email per vessel bundling every currently-open finding
#      touched this run (new + still-open reminders together), not one mail
#      per rule/date — recipients come from VesselNotificationRecipient
#      (notif_type='data_quality'), seeded via import_notification_recipients.py.
#
# Run from repo root: python -m backend.data_quality.daily_job
# ===========================================================================
import logging
from datetime import date, datetime, timedelta

from ..database import SessionLocal
from ..models import DataQualityFinding, Vessel, VesselNotificationRecipient
from ..reporting.email_service import send_email
from .checks import run_checks_for_date

log = logging.getLogger(__name__)

RULE_LABELS = {
    "missing_weather": "Missing weather data (BF Wind / Sig. Wave Height) on a steaming day",
    "missing_cp_instruction": "Missing CP instruction in remarks (Noon at sea / EOSP)",
    "missing_fuel": "Zero fuel logged across every grade on a real steaming day",
}


def _upsert_open_finding(db, vessel_imo, source, report_date, rule_key, detail):
    row = (
        db.query(DataQualityFinding)
        .filter_by(vessel_imo=vessel_imo, source_id=source, report_date=report_date, rule_key=rule_key)
        .first()
    )
    if row is None:
        row = DataQualityFinding(vessel_imo=vessel_imo, source_id=source, report_date=report_date, rule_key=rule_key)
        db.add(row)
    row.status = "open"
    row.detail = detail
    row.last_checked_at = datetime.utcnow()
    return row


def _resolve_finding(db, row):
    row.status = "resolved"
    row.resolved_at = datetime.utcnow()
    row.last_checked_at = datetime.utcnow()


def _dates_to_check(db, vessel_imo, yesterday):
    dates = {yesterday}
    open_dates = (
        db.query(DataQualityFinding.report_date)
        .filter_by(vessel_imo=vessel_imo, status="open")
        .distinct()
        .all()
    )
    dates.update(d for (d,) in open_dates)
    return sorted(dates)


def build_digest_html(vessel_name, entries):
    """Pure rendering, no DB access — shared by the real job (_send_digest,
    fed from DataQualityFinding rows) and test_send.py (fed straight from
    run_checks_for_date's live output, so a template preview can be sent
    without writing any finding state). `entries`: list of dicts with keys
    source_id, rule_key, report_date, detail, notify_count."""
    by_rule = {}
    for e in entries:
        by_rule.setdefault(e["rule_key"], []).append(e)

    lines = [
        f"<h3>Data Quality Alert &mdash; {vessel_name}</h3>",
        "<p>The following mandatory data is missing or incomplete. Please review and "
        "correct the noon reports for the listed dates/voyages.</p>",
    ]
    for rule_key, es in by_rule.items():
        lines.append(f"<p><b>{RULE_LABELS.get(rule_key, rule_key)}</b></p><ul>")
        for e in sorted(es, key=lambda x: x["report_date"]):
            detail = e.get("detail") or {}
            extra = detail.get("voyages") or detail.get("logs") or []
            extra_str = f" (voyages/logs: {', '.join(extra)})" if extra else ""
            resend_note = " &mdash; <i>reminder, still unresolved</i>" if (e.get("notify_count") or 0) > 0 else ""
            lines.append(f"<li>{e['source_id'].upper()} &mdash; {e['report_date']}{extra_str}{resend_note}</li>")
        lines.append("</ul>")

    return "\n".join(lines)


def _send_digest(db, vessel_imo, open_rows):
    rec = (
        db.query(VesselNotificationRecipient)
        .filter_by(vessel_imo=vessel_imo, notif_type="data_quality")
        .first()
    )
    if not rec or not rec.to_emails:
        log.warning(f"No data_quality recipients configured for vessel {vessel_imo} — skipping email ({len(open_rows)} open finding(s)).")
        return False

    vessel = db.query(Vessel).filter_by(imo_number=vessel_imo).first()
    vessel_name = vessel.vessel_name if vessel else vessel_imo

    entries = [
        {
            "source_id": row.source_id, "rule_key": row.rule_key,
            "report_date": row.report_date, "detail": row.detail,
            "notify_count": row.notify_count or 0,
        }
        for row in open_rows
    ]
    html = build_digest_html(vessel_name, entries)
    ok = send_email(
        subject=f"[Data Quality] {vessel_name} — missing mandatory data",
        html_content=html,
        recipients=rec.to_emails,
        cc_recipients=rec.cc_emails,
    )
    if ok:
        for row in open_rows:
            row.last_notified_at = datetime.utcnow()
            row.notify_count = (row.notify_count or 0) + 1
    return ok


def run_daily_data_quality_check():
    db = SessionLocal()
    try:
        yesterday = date.today() - timedelta(days=1)
        vessels = (
            db.query(Vessel)
            .filter((Vessel.wni_enabled.is_(True)) | (Vessel.mari_enabled.is_(True)))
            .all()
        )

        vessels_checked = vessels_mailed = 0
        for vessel in vessels:
            imo = vessel.imo_number
            vessels_checked += 1
            check_dates = _dates_to_check(db, imo, yesterday)

            touched_open_rows = []
            for report_date in check_dates:
                findings = run_checks_for_date(db, imo, report_date)

                existing_open = (
                    db.query(DataQualityFinding)
                    .filter_by(vessel_imo=imo, report_date=report_date, status="open")
                    .all()
                )
                existing_by_key = {(r.source_id, r.rule_key): r for r in existing_open}

                for (source, rule_key), detail in findings.items():
                    row = _upsert_open_finding(db, imo, source, report_date, rule_key, detail)
                    touched_open_rows.append(row)
                    existing_by_key.pop((source, rule_key), None)

                # Left over = was open before, not found missing this pass -> corrected.
                for row in existing_by_key.values():
                    _resolve_finding(db, row)

            db.flush()
            if touched_open_rows:
                if _send_digest(db, imo, touched_open_rows):
                    vessels_mailed += 1

        db.commit()
        log.info(
            f"Data quality daily check complete for {yesterday} "
            f"— {vessels_checked} vessels checked, {vessels_mailed} mailed."
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    run_daily_data_quality_check()
