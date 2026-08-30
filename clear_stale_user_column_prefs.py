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

NOTE: uses raw SQL (engine.execute), not the ORM. UserColumnPreference.user_id
is a FK to `users.id`, but the `User` model lives in backend/auth.py (kept
separate from models.py to avoid a circular import — see CLAUDE.md) and this
script never imports it. SQLAlchemy's ORM delete needs to resolve that FK
when sorting tables, which fails with NoReferencedTableError if `User` was
never mapped in this process. Raw SQL sidesteps the ORM mapper entirely, so
it doesn't matter whether `User` has been imported.

Run once on production:

    python clear_stale_user_column_prefs.py
"""

from sqlalchemy import text
from backend.database import engine

SOURCE = "mari_apps"
TARGET_USER_IDS = (1, 5)


def main():
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT user_id, vessel_imo, column_prefs FROM user_column_preferences "
                "WHERE source = :source AND user_id = ANY(:user_ids)"
            ),
            {"source": SOURCE, "user_ids": list(TARGET_USER_IDS)},
        ).fetchall()

        if not rows:
            print("No matching rows found — nothing to clear.")
            return

        for r in rows:
            visible = (r.column_prefs or {}).get("visible", [])
            print(f"Deleting: user_id={r.user_id} vessel_imo={r.vessel_imo} (had {len(visible)} visible columns)")

        result = conn.execute(
            text(
                "DELETE FROM user_column_preferences "
                "WHERE source = :source AND user_id = ANY(:user_ids)"
            ),
            {"source": SOURCE, "user_ids": list(TARGET_USER_IDS)},
        )
        print(f"Done. Cleared {result.rowcount} stale personal preference row(s).")


if __name__ == "__main__":
    main()
