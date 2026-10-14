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

# Accent color per rule — same red/amber/green dot convention already used
# for the Compliance/Errors columns in the live dashboard (AnalysisTable.jsx),
# so the email reads consistently with the app rather than inventing a new
# color language. missing_fuel is red (directly skews CP fuel figures),
# the other two are amber (data-completeness gaps, not a confirmed verdict
# problem on their own).
RULE_ACCENT = {
    "missing_weather": "#d4a02a",
    "missing_cp_instruction": "#d4a02a",
    "missing_fuel": "#e05050",
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


def _entry_row_html(e, accent):
    detail = e.get("detail") or {}
    extra = detail.get("voyages") or detail.get("logs") or []
    extra_html = (
        f'<span style="color:#5a7fa8;"> &middot; {", ".join(extra)}</span>' if extra else ""
    )
    is_reminder = (e.get("notify_count") or 0) > 0
    badge = (
        '<span style="display:inline-block;margin-left:8px;padding:1px 8px;border-radius:10px;'
        'font-size:10.5px;font-weight:700;background:rgba(212,160,42,0.15);color:#9a7418;'
        'border:1px solid rgba(212,160,42,0.35);">REMINDER</span>'
        if is_reminder else ""
    )
    return f"""
      <tr>
        <td style="padding:8px 0;border-bottom:1px solid #e7ecf2;white-space:nowrap;vertical-align:top;">
          <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:{accent};margin-right:8px;vertical-align:middle;"></span>
          <span style="font-weight:600;color:#1a2b3c;font-size:12.5px;">{e['source_id'].upper()}</span>
        </td>
        <td style="padding:8px 0;border-bottom:1px solid #e7ecf2;color:#1a2b3c;font-size:12.5px;vertical-align:top;">
          {e['report_date']}{extra_html}{badge}
        </td>
      </tr>"""


def build_digest_html(vessel_name, entries):
    """Pure rendering, no DB access — shared by the real job (_send_digest,
    fed from DataQualityFinding rows) and test_send.py (fed straight from
    run_checks_for_date's live output, so a template preview can be sent
    without writing any finding state). `entries`: list of dicts with keys
    source_id, rule_key, report_date, detail, notify_count.

    Table-based layout with everything inline (no <style> block, no external
    CSS/images) — Outlook and most webmail clients strip or ignore anything
    that isn't inline, so this is the only reliable way to style an email."""
    by_rule = {}
    for e in entries:
        by_rule.setdefault(e["rule_key"], []).append(e)

    total_findings = len(entries)
    total_reports = sum(e.get("detail", {}).get("count", 1) for e in entries)
    rule_count = len(by_rule)

    sections = []
    for rule_key, es in by_rule.items():
        accent = RULE_ACCENT.get(rule_key, "#5a7fa8")
        rows_html = "".join(_entry_row_html(e, accent) for e in sorted(es, key=lambda x: x["report_date"]))
        sections.append(f"""
        <tr>
          <td style="padding:22px 0 10px;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
              <tr>
                <td style="border-left:3px solid {accent};padding-left:12px;">
                  <span style="font-size:13.5px;font-weight:700;color:#1a2b3c;">{RULE_LABELS.get(rule_key, rule_key)}</span>
                </td>
              </tr>
            </table>
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin-top:8px;">
              <tr>
                <td style="font-size:11px;font-weight:700;color:#8696a8;text-transform:uppercase;letter-spacing:0.03em;padding-bottom:4px;width:90px;">Source</td>
                <td style="font-size:11px;font-weight:700;color:#8696a8;text-transform:uppercase;letter-spacing:0.03em;padding-bottom:4px;">Date</td>
              </tr>
              {rows_html}
            </table>
          </td>
        </tr>""")

    body = "".join(sections)

    html = f"""\
<div style="background:#eef2f7;padding:24px 0;font-family:Aptos,Arial,Helvetica,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td align="center">
        <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:10px;overflow:hidden;box-shadow:0 1px 3px rgba(20,30,45,0.08);">
          <tr>
            <td style="background:#1f3864;padding:20px 28px;">
              <span style="color:#ffffff;font-size:16px;font-weight:700;">Data Quality Alert</span><br/>
              <span style="color:#9fb3cc;font-size:13px;">{vessel_name}</span>
            </td>
          </tr>
          <tr>
            <td style="padding:20px 28px 0;">
              <p style="margin:0;color:#3a4a5c;font-size:13px;line-height:1.5;">
                The mandatory data below is missing or incomplete for the dates/voyages listed.
                Please review and correct the corresponding noon reports.
              </p>
              <table role="presentation" cellpadding="0" cellspacing="0" style="margin-top:14px;">
                <tr>
                  <td style="background:#f3f6fa;border-radius:6px;padding:8px 14px;">
                    <span style="font-size:12px;color:#5a7fa8;">{rule_count} issue type{'s' if rule_count != 1 else ''} &middot; {total_findings} finding{'s' if total_findings != 1 else ''} &middot; {total_reports} report{'s' if total_reports != 1 else ''} affected</span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:0 28px 20px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
                {body}
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:16px 28px;background:#f8fafc;border-top:1px solid #e7ecf2;">
              <span style="font-size:11px;color:#8696a8;">
                Automated message from the Vessel Performance data-quality check. A "REMINDER" tag
                means this was already flagged previously and is still unresolved as of today's check.
              </span>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</div>"""

    return html


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
        # Only vessels with an ACTIVE data_quality recipient row are actually
        # checked/mailed — manager approved a 5-vessel trial first (2026-10),
        # see TRIAL_VESSELS in import_notification_recipients.py. The other
        # 9 vessels' recipient rows are seeded but is_active=False, so they're
        # excluded here entirely rather than checked-but-not-mailed (no point
        # writing DataQualityFinding rows for a vessel nobody will see).
        vessels = (
            db.query(Vessel)
            .join(
                VesselNotificationRecipient,
                VesselNotificationRecipient.vessel_imo == Vessel.imo_number,
            )
            .filter(
                VesselNotificationRecipient.notif_type == "data_quality",
                VesselNotificationRecipient.is_active.is_(True),
            )
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
