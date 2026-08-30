"""
clear_stale_user_column_prefs.py
--------------------------------
One-off script: clears stale personal column-visibility preferences
(`user_column_preferences`) for specific users, so their account falls back
to the (now-correct) admin/Global column default instead of an old snapshot
that predates recent column additions.

Background: a user's personal preference (if non-empty) completely
overrides the admin `vessel_column_defaults` / Global default for their own
view — that's by design (personal customization), but it means any account
that toggled columns before a batch of new columns was added keeps seeing
its own outdated set indefinitely, with no UI way to reset it. This script
does the reset directly; a proper "Reset to Default" button has also been
added to the picker so this doesn't require a manual DB fix going forward.

Only deletes rows for TARGET_USER_IDS + SOURCE below — never touches
`vessel_column_defaults` (the shared admin default) or any other user's
personal preferences.

Run once on production:

    python clear_stale_user_column_prefs.py
"""

from backend.database import SessionLocal
from backend.models import UserColumnPreference

SOURCE = "mari_apps"
TARGET_USER_IDS = [1, 5]


def main():
    db = SessionLocal()
    try:
        rows = db.query(UserColumnPreference).filter(
            UserColumnPreference.source == SOURCE,
            UserColumnPreference.user_id.in_(TARGET_USER_IDS),
        ).all()

        if not rows:
            print("No matching rows found — nothing to clear.")
            return

        for r in rows:
            print(
                f"Deleting: user_id={r.user_id} vessel_imo={r.vessel_imo} "
                f"(had {len(r.column_prefs.get('visible', []))} visible columns)"
            )
            db.delete(r)

        db.commit()
        print(f"Done. Cleared {len(rows)} stale personal preference row(s).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
