# ===========================================================================
# import_voyage_completion_recipients.py
#
# Idempotent (safe to re-run) loader for the "voyage_completion" notif_type on
# vessel_notification_recipients. Every vessel that has an ACTIVE data_quality
# recipient row (import_notification_recipients.py) gets a voyage_completion
# row with the SAME TO/CC/From, copied from the DB at run time — i.e. the
# voyage-completion mail goes to the same actual recipients as the Data
# Quality mail, for the whole fleet.
#
# The only difference: the 4 AMNS-prefixed vessels also get 2 AMNS client
# addresses (manager request 2026-10) added to TO, for this mail only.
#
# Re-running re-copies the data_quality lists, so after changing a vessel's
# data_quality recipients, re-run this to carry the change over. A vessel is
# only mailed if it is MariApps-scraped and its voyage meets the data
# threshold (see backend/mariapps_pipeline/voyage_completion_mail.py).
#
# Run from repo root: python -m import_voyage_completion_recipients
# ===========================================================================
import logging

from backend.database import SessionLocal
from backend.models import Vessel, VesselNotificationRecipient

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
log = logging.getLogger(__name__)

NOTIF_TYPE = "voyage_completion"
SOURCE_TYPE = "data_quality"

# Voyage-completion-only recipients (manager request 2026-10), AMNS vessels.
AMNS_EXTRA_TO = ["ashish.bhatnagar@amns.in", "anuj.kaushik@amns.in"]


def _dedupe(addrs):
    seen, out = set(), []
    for a in addrs:
        k = a.strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(a.strip())
    return out


def run():
    db = SessionLocal()
    loaded = 0
    try:
        sources = (
            db.query(VesselNotificationRecipient)
            .filter(VesselNotificationRecipient.notif_type == SOURCE_TYPE,
                    VesselNotificationRecipient.is_active.is_(True))
            .all()
        )
        for src in sources:
            vessel = db.query(Vessel).filter(Vessel.imo_number == src.vessel_imo).first()
            name = vessel.vessel_name if vessel else src.vessel_imo

            to = list(src.to_emails or [])
            if vessel and vessel.vessel_name.upper().startswith("AMNS"):
                to += AMNS_EXTRA_TO

            row = (
                db.query(VesselNotificationRecipient)
                .filter(
                    VesselNotificationRecipient.vessel_imo == src.vessel_imo,
                    VesselNotificationRecipient.notif_type == NOTIF_TYPE,
                )
                .first()
            )
            if row is None:
                row = VesselNotificationRecipient(vessel_imo=src.vessel_imo, notif_type=NOTIF_TYPE)
                db.add(row)

            row.from_email = src.from_email
            row.to_emails = _dedupe(to)
            row.cc_emails = _dedupe(list(src.cc_emails or []))
            row.is_active = True
            loaded += 1
            log.info(f"{name}: TO={row.to_emails} CC={row.cc_emails}")

        db.commit()
        log.info(f"Loaded/updated {loaded} vessel_notification_recipients rows (notif_type={NOTIF_TYPE}).")
        if loaded == 0:
            log.warning("No active data_quality recipient rows found — run import_notification_recipients first.")
    finally:
        db.close()


if __name__ == "__main__":
    run()
