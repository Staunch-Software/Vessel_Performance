"""
Voyage-completion mail (manager request 2026-10, AMNS fleet): the Voyage
Audit Report PDF for the voyage that just ended, sent once a brand-new
MariApps EOSP log is saved (see mariapps_persistence.py's save_log()).

The body is a short note only — voyage, ports, dates, "report attached"; the
report itself is the same PDF the Logbook+ download button produces (see
voyage_report_pdf.py). Deliberately standalone: nothing to do with the
Data Quality digest (backend/data_quality/) and it does not touch
DataQualityFinding/Thread.

Recipients come from VesselNotificationRecipient (notif_type=
"voyage_completion"), seeded via import_voyage_completion_recipients.py for
just the 4 AMNS-prefixed vessels — vessels with no row for this notif_type
(or an inactive one) are silently skipped, so this never fires for the rest
of the fleet without a separate, deliberate seeding step.
"""
import html
import logging
import os
import shutil

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import AnalysisData, VesselNotificationRecipient
from ..reporting.email_service import send_email
from .voyage_report_pdf import render_voyage_pdf

log = logging.getLogger(__name__)


# A voyage must have real data behind it to be worth a report: short port
# shifts (e.g. a 30-min BOSP->EOSP move, 0 nm) produce an empty Voyage Audit
# Report. Both thresholds env-overridable.
MIN_DISTANCE_NM = float(os.getenv("VOYAGE_MAIL_MIN_DISTANCE_NM", "50"))
MIN_REPORTS = int(os.getenv("VOYAGE_MAIL_MIN_REPORTS", "3"))


def voyage_data_summary(db: Session, vessel_imo, voyage_no):
    """(report_count, total_distance_nm, qualifies) for this voyage's MariApps rows."""
    n, dist = db.query(func.count(AnalysisData.id), func.coalesce(func.sum(AnalysisData.Distance_nm), 0)).filter(
        AnalysisData.vessel_imo == vessel_imo,
        AnalysisData.Voyage_No == voyage_no,
        AnalysisData.source_id == "mari_apps",
    ).one()
    dist = float(dist or 0)
    return n, dist, (n >= MIN_REPORTS and dist >= MIN_DISTANCE_NM)


def _fmt_date(d):
    return d.strftime("%d %b %Y") if d else "—"


def _voyage_facts(db: Session, vessel_imo, voyage_no, from_port):
    """Ports + first/last report date of this voyage's MariApps rows."""
    q = db.query(AnalysisData).filter(
        AnalysisData.vessel_imo == vessel_imo,
        AnalysisData.Voyage_No == voyage_no,
        AnalysisData.source_id == "mari_apps",
    )
    start, end = db.query(func.min(AnalysisData.Date), func.max(AnalysisData.Date)).filter(
        AnalysisData.vessel_imo == vessel_imo,
        AnalysisData.Voyage_No == voyage_no,
        AnalysisData.source_id == "mari_apps",
    ).one()
    to_row = q.filter(AnalysisData.To_Port.isnot(None)).order_by(AnalysisData.Date.desc()).first()
    return {
        "from_port": (from_port or "").strip(),
        "to_port": (to_row.To_Port or "").strip() if to_row else "",
        "start": start,
        "end": end,
    }


def _build_html(vessel_name, voyage_no, facts, has_attachment):
    e = html.escape
    route = ""
    if facts["from_port"] and facts["to_port"]:
        route = f"{e(facts['from_port'])} to {e(facts['to_port'])}"
    elif facts["from_port"]:
        route = f"From {e(facts['from_port'])}"
    elif facts["to_port"]:
        route = f"To {e(facts['to_port'])}"

    rows = [f"<p style=\"margin:0 0 6px;\">Voyage: <strong>{e(str(voyage_no or '—'))}</strong></p>"]
    if route:
        rows.append(f"<p style=\"margin:0 0 6px;\">Route: <strong>{route}</strong></p>")
    if facts["start"] or facts["end"]:
        rows.append(
            f"<p style=\"margin:0 0 6px;\">Period: <strong>{_fmt_date(facts['start'])} – "
            f"{_fmt_date(facts['end'])}</strong></p>"
        )
    closing = (
        "The Voyage Audit Report is attached."
        if has_attachment
        else "The Voyage Audit Report could not be generated automatically; "
             "please download it from Logbook+."
    )
    return f"""
<div style="font-family:Arial,sans-serif;font-size:14px;color:#334155;max-width:560px;">
  <p style="margin:0 0 14px;">Voyage completed for <strong>{e(str(vessel_name))}</strong>.</p>
  {''.join(rows)}
  <p style="margin:14px 0 0;">{closing}</p>
  <p style="margin:18px 0 0;font-size:11px;color:#8696a8;">Automated message from the Vessel Performance system.</p>
</div>"""


def maybe_send_voyage_completion_mail(db: Session, vessel_imo, vessel_name, log_number, voyage_no, log_date, from_port=None, test_to=None):
    """Sends the mail iff an active voyage_completion recipient row exists for
    this vessel. Caller is responsible for only calling this for a genuinely
    new (not corrected/re-saved) EOSP log — see save_log().

    test_to: preview mode (test_voyage_completion.py) — send ONLY to this
    address, ignore the stored recipient rows entirely (no TO/CC to the real
    list), and tag the subject [TEST]."""
    n_reports, dist_nm, qualifies = voyage_data_summary(db, vessel_imo, voyage_no)
    if not qualifies:
        log.info(
            f"Voyage-completion mail skipped for {vessel_name} {voyage_no}: only {n_reports} report(s), "
            f"{dist_nm:.0f} nm (needs >= {MIN_REPORTS} reports and >= {MIN_DISTANCE_NM:.0f} nm)."
        )
        return False

    if test_to:
        to_list, cc_list, tag = [test_to], [], "[TEST] "
    else:
        rec = (
            db.query(VesselNotificationRecipient)
            .filter_by(vessel_imo=vessel_imo, notif_type="voyage_completion", is_active=True)
            .first()
        )
        if not rec or not rec.to_emails:
            return False
        to_list, cc_list, tag = rec.to_emails, rec.cc_emails, ""

    facts = _voyage_facts(db, vessel_imo, voyage_no, from_port)

    pdf_path = render_voyage_pdf(vessel_imo, vessel_name, voyage_no)
    if not pdf_path:
        log.warning(f"Voyage report PDF missing for {vessel_name} {voyage_no}; sending mail without attachment.")

    try:
        ok = send_email(
            subject=f"{tag}[Voyage Completion] {vessel_name} — Voyage {voyage_no} Summary Report",
            html_content=_build_html(vessel_name, voyage_no, facts, bool(pdf_path)),
            recipients=to_list,
            cc_recipients=cc_list,
            attachments=[pdf_path] if pdf_path else None,
        )
    finally:
        if pdf_path:
            shutil.rmtree(os.path.dirname(pdf_path), ignore_errors=True)
    if not ok:
        log.warning(f"Voyage-completion mail failed to send for {vessel_name} log {log_number}.")
    return ok
