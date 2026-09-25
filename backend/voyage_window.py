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
