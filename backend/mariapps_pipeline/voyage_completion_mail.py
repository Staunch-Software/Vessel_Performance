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
# Report. Measured over the SAME BOSP->EOSP window the report itself uses
# (/voyage/summary), not every row carrying the voyage number — later in-port
# days under the same number would otherwise make an empty report look big.
# Both thresholds env-overridable.
MIN_DISTANCE_NM = float(os.getenv("VOYAGE_MAIL_MIN_DISTANCE_NM", "50"))
MIN_DURATION_H = float(os.getenv("VOYAGE_MAIL_MIN_DURATION_H", "12"))


def voyage_data_summary(vessel_imo, voyage_no):
    """(distance_nm, duration_h, qualifies) for the report's sea-passage window.
    Uses its own short-lived session: get_voyage_summary relabels rows
    in memory (never to be committed), so it must not share the caller's."""
    from api.routes.vessel_routes import get_voyage_summary
    from ..database import SessionLocal

    s = SessionLocal()
    try:
        summ = get_voyage_summary(str(voyage_no), str(vessel_imo), "mari_apps", s)
    except Exception:
        return 0.0, 0.0, False
    finally:
        s.rollback()
        s.close()
    dist = float(summ.get("Distance_nm") or 0)
    dur = float(summ.get("Duration_h") or 0)
    return dist, dur, (dist >= MIN_DISTANCE_NM and dur >= MIN_DURATION_H)


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


def _tidy_port(p):
    """'Paradip port {INPPT},India' -> 'Paradip port (INPPT), India'."""
    return " ".join(p.replace("{", "(").replace("}", ")").replace(",", ", ").split())


def _build_html(vessel_name, voyage_no, facts, has_attachment):
    e = html.escape
    facts = {**facts, "from_port": _tidy_port(facts["from_port"]), "to_port": _tidy_port(facts["to_port"])}
    route = ""
    if facts["from_port"] and facts["to_port"]:
        route = f"{e(facts['from_port'])} to {e(facts['to_port'])}"
    elif facts["from_port"]:
        route = f"From {e(facts['from_port'])}"
    elif facts["to_port"]:
        route = f"To {e(facts['to_port'])}"

    def row(label, value):
        return (
            '<tr>'
            f'<td style="padding:9px 0;width:92px;font-size:12px;color:#64748b;'
            f'text-transform:uppercase;letter-spacing:.4px;border-bottom:1px solid #eef2f7;">{label}</td>'
            f'<td style="padding:9px 0;font-size:14px;color:#0f172a;font-weight:600;'
            f'border-bottom:1px solid #eef2f7;">{value}</td>'
            '</tr>'
        )

    rows = [row("Voyage", e(str(voyage_no or "—")))]
    if route:
        rows.append(row("Route", route.replace(" to ", " &rarr; ")))
    if facts["start"] or facts["end"]:
        rows.append(row("Period", f"{_fmt_date(facts['start'])} &ndash; {_fmt_date(facts['end'])}"))

    if has_attachment:
        notice = (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            'style="margin-top:20px;background:#f1f5fb;border:1px solid #d6e0f0;border-radius:8px;">'
            '<tr><td style="padding:14px 16px;font-size:13.5px;color:#1f3864;">'
            '<strong>&#128206; Voyage Audit Report attached (PDF)</strong><br>'
            '<span style="font-size:12px;color:#5b6b85;">Speed &amp; weather analysis, fuel consumption '
            'and charter-party performance for this voyage.</span>'
            '</td></tr></table>'
        )
    else:
        notice = (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            'style="margin-top:20px;background:#fff7ed;border:1px solid #fed7aa;border-radius:8px;">'
            '<tr><td style="padding:14px 16px;font-size:13px;color:#9a3412;">'
            'The Voyage Audit Report could not be generated automatically. '
            'Please download it from Logbook+.'
            '</td></tr></table>'
        )

    return f"""
<div style="background:#f4f6fa;padding:24px 12px;font-family:Segoe UI,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
         style="max-width:580px;margin:0 auto;background:#ffffff;border:1px solid #e2e8f0;border-radius:10px;overflow:hidden;">
    <tr><td style="background:#1f3864;padding:22px 28px;">
      <div style="font-size:11px;letter-spacing:1.2px;color:#9db4dc;text-transform:uppercase;">Voyage Completion</div>
      <div style="font-size:22px;font-weight:700;color:#ffffff;margin-top:4px;">{e(str(vessel_name))}</div>
    </td></tr>
    <tr><td style="padding:24px 28px 26px;">
      <p style="margin:0 0 14px;font-size:14px;color:#334155;">
        The voyage below has been completed. Summary details:
      </p>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
        {''.join(rows)}
      </table>
      {notice}
    </td></tr>
    <tr><td style="padding:14px 28px;background:#f8fafc;border-top:1px solid #e2e8f0;">
      <span style="font-size:11px;color:#8696a8;">Automated message from the Vessel Performance system.</span>
    </td></tr>
  </table>
</div>"""


def maybe_send_voyage_completion_mail(db: Session, vessel_imo, vessel_name, log_number, voyage_no, log_date, from_port=None, test_to=None):
    """Sends the mail iff an active voyage_completion recipient row exists for
    this vessel. Caller is responsible for only calling this for a genuinely
    new (not corrected/re-saved) EOSP log — see save_log().

    test_to: preview mode (test_voyage_completion.py) — send ONLY to this
    address, ignore the stored recipient rows entirely (no TO/CC to the real
    list), and tag the subject [TEST]."""
    dist_nm, dur_h, qualifies = voyage_data_summary(vessel_imo, voyage_no)
    if not qualifies:
        log.info(
            f"Voyage-completion mail skipped for {vessel_name} {voyage_no}: sea passage is "
            f"{dist_nm:.0f} nm / {dur_h:.1f} h (needs >= {MIN_DISTANCE_NM:.0f} nm and >= {MIN_DURATION_H:.0f} h)."
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
