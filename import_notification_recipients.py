# ===========================================================================
# import_notification_recipients.py
#
# One-off (idempotent — safe to re-run) loader for vessel_notification_
# recipients, seeded from the client's per-vessel TO/CC list (2026-10). Same
# convention as import_cp_description.py: wipes and reloads rows for the
# notif_type being loaded rather than merging field-by-field, so re-running
# after an email-list change always reflects exactly this file's contents.
#
# Run from repo root: python -m import_notification_recipients
# (or) python import_notification_recipients.py
# ===========================================================================
import logging

from backend.database import SessionLocal
from backend.models import Vessel, VesselNotificationRecipient

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
log = logging.getLogger(__name__)

FROM_EMAIL = "data@ozellar.com"

# vessel_name (must match vessels.vessel_name exactly — see mariapps_pipeline.py's
# VESSEL_LIST for the canonical spellings) -> {"to": [...], "cc": [...]}
RECIPIENTS = {
    "AM KIRTI":       {"to": ["amkirti@ozellar.com", "pavan@ozellar.com", "kunalchandra@ozellar.com", "meenakshy@ozellar.com"],          "cc": ["tmamkirti@ozellar.com", "techdevops@ozellar.com"]},
    "AM TARANG":      {"to": ["amtarang@ozellar.com", "pavan@ozellar.com", "kunalchandra@ozellar.com", "meenakshy@ozellar.com"],         "cc": ["tmamtarang@ozellar.com", "techdevops@ozellar.com"]},
    "GCL NARMADA":    {"to": ["gclnarmada@ozellar.com", "pavan@ozellar.com", "kunalchandra@ozellar.com", "meenakshy@ozellar.com"],       "cc": ["tmgclnarmada@ozellar.com", "techdevops@ozellar.com"]},
    "GCL SABARMATI":  {"to": ["gclsabarmati@ozellar.com", "pavan@ozellar.com", "kunalchandra@ozellar.com", "meenakshy@ozellar.com"],     "cc": ["tmgclsabarmati@ozellar.com", "techdevops@ozellar.com"]},
    "GCL FOS":        {"to": ["gclfos@ozellar.com", "gauravsingh.r@ozellar.com", "kunalchandra@ozellar.com", "meenakshy@ozellar.com"],   "cc": ["tmgclfos@ozellar.com", "techdevops@ozellar.com"]},
    "GCL YAMUNA":     {"to": ["gclyamuna@ozellar.com", "gauravsingh.r@ozellar.com", "kunalchandra@ozellar.com", "meenakshy@ozellar.com"],"cc": ["tmgclyamuna@ozellar.com", "techdevops@ozellar.com"]},
    "GCL GANGA":      {"to": ["gclganga@ozellar.com", "gauravsingh.r@ozellar.com", "kunalchandra@ozellar.com", "meenakshy@ozellar.com"], "cc": ["tmgclganga@ozellar.com", "techdevops@ozellar.com"]},
    "GCL SARASWATI":  {"to": ["gclsaraswati@ozellar.com", "abhinav.s@ozellar.com", "kunalchandra@ozellar.com", "meenakshy@ozellar.com"], "cc": ["tmgclsaraswati@ozellar.com", "techdevops@ozellar.com"]},
    "AMNS POLAR":     {"to": ["amns.polar@gtmailplus.com", "abhinav.s@ozellar.com", "kunalchandra@ozellar.com", "meenakshy@ozellar.com"],"cc": ["tmamnspolar@ozellar.com", "techdevops@ozellar.com"]},
    "AMNS TUFMAX":    {"to": ["amnstufmax@ozellar.com", "abhinav.s@ozellar.com", "kunalchandra@ozellar.com", "meenakshy@ozellar.com"],   "cc": ["tmamnstufmax@ozellar.com", "techdevops@ozellar.com"]},
    "AMNSI MAXIMUS":  {"to": ["amnsimaximus@gtmailplus.com", "Murtuza@ozellar.com", "kunalchandra@ozellar.com", "meenakshy@ozellar.com"],"cc": ["tmamnsimaximus@ozellar.com", "techdevops@ozellar.com"]},
    "AM UMANG":       {"to": ["amumang@ozellar.com", "Murtuza@ozellar.com", "kunalchandra@ozellar.com", "meenakshy@ozellar.com"],        "cc": ["tmamumang@ozellar.com", "techdevops@ozellar.com"]},
    "GCL TAPI":       {"to": ["gcltapi@ozellar.com", "Murtuza@ozellar.com", "kunalchandra@ozellar.com", "meenakshy@ozellar.com"],        "cc": ["tmgcltapi@ozellar.com", "techdevops@ozellar.com"]},
    "AMNSI STALLION":  {"to": ["amnsistallion@gtmailplus.com", "Murtuza@ozellar.com", "kunalchandra@ozellar.com", "meenakshy@ozellar.com"], "cc": ["tmamnsistallion@ozellar.com", "techdevops@ozellar.com"]},
}

NOTIF_TYPE = "data_quality"

# Manager approved a 5-vessel trial first (2026-10 WhatsApp reply: "Let's send
# to Kirti / Tarang / Narmada / Maximus / Polar as trial. Once correctly
# implemented, will do for all vessels.") — trial confirmed 2026-10, rolled
# out fleet-wide: every vessel in RECIPIENTS is now active. Kept as a named
# set (rather than always-True) so a future partial rollback/rollout is a
# one-line change here, same as the original trial was.
TRIAL_VESSELS = set(RECIPIENTS.keys())


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
            row.to_emails = emails["to"]
            row.cc_emails = emails["cc"]
            row.is_active = vessel_name in TRIAL_VESSELS
            loaded += 1

        db.commit()
        log.info(f"Loaded/updated {loaded} vessel notification-recipient rows (notif_type={NOTIF_TYPE}).")
        log.info(f"Active (trial) vessels: {sorted(TRIAL_VESSELS)} — the rest are seeded but inactive until the trial is confirmed.")
        if missing_vessel:
            log.warning(f"No matching vessels row for: {missing_vessel} — check vessel_name spelling against the vessels table.")
    finally:
        db.close()


if __name__ == "__main__":
    run()
