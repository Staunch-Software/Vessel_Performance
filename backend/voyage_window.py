"""
Shared BOSP/EOSP voyage-window finder.

WHY THIS EXISTS: cp_routes.py's live Charter-Party Performance table and
vessel_routes.py's /voyage/series (which feeds the PDF Voyage Audit Report)
each computed a voyage's departure/arrival window with their own, separately
written implementation of the same idea. Found 2026-09 (GCL SARASWATI
003/B2): they drifted apart at the edges — one extra day and ~15nm of
difference on a real, already-complete voyage — so the live table and the
PDF report never quite agreed even once their downstream calculation math
was unified. This module is now the ONE place that logic lives; both
routes call it instead of reimplementing it.
"""


def find_bosp_eosp_window(dated_rows):
    """
    dated_rows: a list of (dt_key, event_type, row) tuples for ONE voyage,
    already sorted chronologically by dt_key (a string like
    "2026-03-30T12:00", directly comparable). `row` is opaque — whatever the
    caller's own row representation is (dict, ORM object, ...); this
    function never touches its fields directly.

    Returns (dep_row, arr_row, dep_dt, arr_dt) for the real BOSP -> EOSP
    passage, or None if there's no usable window:
      - no EOSP at all (voyage not yet complete), or
      - the computed departure doesn't precede the arrival (e.g. the only
        "departure" available — because no BOSP precedes the EOSP — turns
        out to BE the EOSP row itself, collapsing the range to nothing).

    Departure resolution: the LAST BOSP that is not after the EOSP (i.e.
    the BOSP immediately preceding this arrival), falling back to the
    voyage's chronologically first row when no such BOSP exists.
    Arrival resolution: the LAST EOSP-tagged row (a corrected/re-submitted
    arrival report wins over an earlier one).
    """
    bosps = [(dt, r) for dt, et, r in dated_rows if et and "BOSP" in et.upper()]
    eosps = [(dt, r) for dt, et, r in dated_rows if et and "EOSP" in et.upper()]
    if not eosps:
        return None

    arr_dt, arr_row = eosps[-1]

    valid_bosps = [(dt, r) for dt, r in bosps if dt <= arr_dt]
    if valid_bosps:
        dep_dt, dep_row = valid_bosps[0]
    else:
        dep_dt, dep_row = dated_rows[0][0], dated_rows[0][2]

    if dep_dt >= arr_dt:
        return None

    return dep_row, arr_row, dep_dt, arr_dt


def nearest_preceding_bosp(context_rows, before_dt):
    """
    Finds the BOSP/COSP-tagged row closest to (but strictly before)
    `before_dt` among `context_rows` — a list of (dt_key, event_type, row)
    tuples in the same opaque shape as find_bosp_eosp_window()'s input, but
    NOT scoped to one voyage: callers pass in whatever immediately precedes
    a voyage's own first row (same vessel + source, any voyage number).

    WHY THIS EXISTS: confirmed 2026-10 (AMNSI MAXIMUS voyage 59B/01, AM
    TARANG voyage 07L/01 pattern) — MariApps/WNI masters commonly log the
    BOSP/Departure Report that truly opens a leg's sea passage under the
    PREVIOUS voyage number, not the new one. When that leg has no
    Noon-at-sea row of its own before its EOSP (a short hop), filtering
    strictly to the new voyage's own Voyage_No leaves the EOSP as the very
    first row available, which collapses find_bosp_eosp_window() to a
    zero-width window even though a real departure event exists — just
    filed under the wrong voyage number.

    Callers: on a collapsed (None) find_bosp_eosp_window() result for a
    voyage that DOES have an EOSP, fetch a small, date-bounded set of rows
    preceding that voyage's own first row, pass them here, and if a row
    comes back, prepend (dt, "BOSP", row) to the voyage's own row list and
    re-run find_bosp_eosp_window() — it now has a genuine departure anchor.
    Returns None (no behavior change for the caller) when nothing
    qualifies, including the case where there's genuinely no earlier data
    at all (e.g. the first-ever ingested report for that vessel/source).
    """
    candidates = [
        (dt, r) for dt, et, r in context_rows
        if et and ("BOSP" in et.upper() or "COSP" in et.upper()) and dt < before_dt
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda x: x[0])
