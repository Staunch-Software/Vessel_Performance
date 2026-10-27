# ===========================================================================
# import_voyage_completion_recipients.py
#
# One-off (idempotent — safe to re-run) loader for the new "voyage_completion"
# notif_type on vessel_notification_recipients — manager request 2026-10,
# AMNS fleet only. Reuses each vessel's existing data_quality TO/CC lists
# (import_notification_recipients.py) as the base, plus 2 extra addresses
# that should get ONLY the voyage-completion mail, added to TO.
#
# Same convention as import_notification_recipients.py: wipes and reloads
# this notif_type's rows rather than merging field-by-field, so re-running
# after an email-list change always reflects exactly this file's contents.
#
# Run from repo root: python -m import_voyage_completion_recipients
# ===========================================================================
import logging

from backend.database import SessionLocal
from backend.models import Vessel, VesselNotificationRecipient

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
log = logging.getLogger(__name__)

FROM_EMAIL = "data@ozellar.com"
NOTIF_TYPE = "voyage_completion"

# Voyage-completion-only recipients (manager request 2026-10) — added to TO
# for all 4 AMNS vessels, on top of each vessel's existing data_quality list.
EXTRA_TO = ["ashish.bhatnagar@amns.in", "anuj.kaushik@amns.in"]

# Base TO/CC lists copied from import_notification_recipients.py's RECIPIENTS
# dict for the 4 AMNS-prefixed vessels — kept as a separate copy here
# (not cross-imported) since this notif_type's list is meant to evolve
# independently of the data_quality one.
RECIPIENTS = {
    "AMNS POLAR":    {"to": ["amns.polar@gtmailplus.com", "abhinav.s@ozellar.com", "kunalchandra@ozellar.com", "meenakshy@ozellar.com"], "cc": ["tmamnspolar@ozellar.com", "techdevops@ozellar.com"]},
    "AMNS TUFMAX":   {"to": ["amnstufmax@ozellar.com", "abhinav.s@ozellar.com", "kunalchandra@ozellar.com", "meenakshy@ozellar.com"],    "cc": ["tmamnstufmax@ozellar.com", "techdevops@ozellar.com"]},
    "AMNSI MAXIMUS": {"to": ["amnsimaximus@gtmailplus.com", "Murtuza@ozellar.com", "kunalchandra@ozellar.com", "meenakshy@ozellar.com"], "cc": ["tmamnsimaximus@ozellar.com", "techdevops@ozellar.com"]},
    "AMNSI STALLION":{"to": ["amnsistallion@gtmailplus.com", "Murtuza@ozellar.com", "kunalchandra@ozellar.com", "meenakshy@ozellar.com"],"cc": ["tmamnsistallion@ozellar.com", "techdevops@ozellar.com"]},
}


def run():
    db = SessionLocal()
    loaded, missing_vessel = 0, []
    try:
        for vessel_name, emails in RECIPIENTS.items():
            vessel = db.query(Vessel).filter(Vessel.vessel_name == vessel_name).first()
            if not vessel:
                missing_vessel.append(vessel_name)
                continue

            row = (
                db.query(VesselNotificationRecipient)
                .filter(
                    VesselNotificationRecipient.vessel_imo == vessel.imo_number,
                    VesselNotificationRecipient.notif_type == NOTIF_TYPE,
                )
                .first()
            )
            if row is None:
                row = VesselNotificationRecipient(vessel_imo=vessel.imo_number, notif_type=NOTIF_TYPE)
                db.add(row)

            row.from_email = FROM_EMAIL
            row.to_emails = emails["to"] + EXTRA_TO
            row.cc_emails = emails["cc"]
            row.is_active = True
            loaded += 1

        db.commit()
        log.info(f"Loaded/updated {loaded} vessel_notification_recipients rows (notif_type={NOTIF_TYPE}).")
        if missing_vessel:
            log.warning(f"No matching vessels row for: {missing_vessel} — check vessel_name spelling against the vessels table.")
    finally:
        db.close()


if __name__ == "__main__":
    run()
