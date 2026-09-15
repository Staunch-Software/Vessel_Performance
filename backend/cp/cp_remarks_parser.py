"""
CP Voyage Remarks parser — turns the free-text "Remarks" box on MariApps'
Position tab (scraped into expanded_mariapps_data.cpx_remarks — see
pipeline/expander.py's _mariapps_remarks_field) into a structured per-day CP
instruction.

WHY THIS EXISTS: the vessel's standing CP warranty (cp_sea_warranty, one row
per vessel x loading condition x speed mode) is a single fixed figure — but
the master's own day-to-day remarks can carry a DIFFERENT instruction for
that specific day (Eco vs Full speed, an ETA-driven full-speed order, a
revised term mid-voyage). A real example that motivated this: a voyage's
13-16 July reports were sailed at Full speed to hold ETA, but the CP
Performance audit compared them against the Economical-speed warranty for
the whole voyage, because there was no per-day override — this module is
that override.

FIVE KNOWN FORMATS — confirmed 2026-09 by sampling real remarks text across
the whole fleet (not just one vessel — every vessel's master phrases this
differently). Don't assume this list is exhaustive; a fleet-wide sample
turned up 3 more formats beyond the original 2 within one pass, so treat an
unparsed remarks entry as "check the raw text", not "definitely no
instruction" (see parse_cp_remarks's own docstring for that same caveat).

FORMAT A (AM TARANG) — condition + speed + combined total + ME/AE split, in
prose with "ABT" (about) qualifiers:
    "LADEN ABT 11.5 KNOTS ON ABT IFO 30.5 MT/DAY (ABT 26.9 MT FOR M/E + ABT 3.6 MT FOR A/E)"
Two lines (one per condition) can appear together on a report logged the
day the vessel's condition/instruction was being restated.

FORMAT B (GCL YAMUNA) — no condition keyword at all (applies regardless of
the report's own condition — see pick_instruction_for_condition), speed +
ME/AE given as separate labeled lines, no combined total or GO figure:
    "INSTRUCTED CP SPEED: 11.5 KTS
     ME CONSUMPTION: 26.5 MT/DAY
     AE CONSUMPTION: 0.1 MT/DAY"
total_mt_day computed as ME + AE.

FORMAT C (GCL FOS / GCL TAPI) — no condition keyword, speed + a COMBINED
ME+AE VLSFO figure (not split) + a genuine, real LSMGO (GO) figure:
    "Instructed CP speed: 11.25 Kts./VLSFO Consumption: 38 MT/DAY(ME + AE) & LSMGO : 0.1 MT"
    "INSTRUCTED CP ECO SPEED: 11.5 KNOTS / VLSFO CONSUMPTION: 30.9 MT ( ME + AE ) / LSMGO CONSUMPTION: 0.2 MT"
This is the ONLY format so far that gives a real GO number instead of no
GO data at all — me_mt_day/ae_mt_day are left None (not split out), and
go_mt_day is populated for real (see the go_mt_day field below).

FORMAT D (a vessel using dash/en-dash separators instead of colons) — like
Format B but with "–"/"-" instead of ":", comma-separated, and an explicit
condition line directly above it:
    "BALLAST
     INSTRUCTED CP SPEED – 13.2 KTS , ME CONSUMPTION -26.0 MT,  AE CONSUMPTION -2.6 MT"

FORMAT E (GCL GANGA) — condition + speed + a COMBINED ME+AE total (not
split), using "//" as the delimiter:
    "LADEN // 11.5 KNOTS// 30.5  MT/DAY (ME+AE)"

NOT an instruction at all — genuinely no numbers, don't try to parse:
  - Narrative-only remarks ("Vessel proceeding to Gijon, Spain at ECO
    speed as per voyage instruction.") — common on AM KIRTI, GCL FOS (on
    days a Format C line isn't also present), GCL SABARMATI.
  - Port/berthing operational logs ("ALL MADE FAST/FWE", "Commence
    Loading", ETA notes) — seen on some vessels, not a CP note of any kind.
These correctly return an empty parse — that's accurate, not a bug.

Every format here is pattern-matched free text a human typed, not a
structured field — treat an unparsed line as "check the raw text", and
resample real remarks before assuming these five formats cover every
master's phrasing fleet-wide.
"""

import re

_INSTRUCTION_RE_A = re.compile(
    r"(?P<condition>LADEN|BALLAST)\s*ABT\s*(?P<speed_kn>[\d.]+)\s*KNOTS?\s*ON\s*ABT\s*IFO\s*"
    r"(?P<total_mt_day>[\d.]+)\s*MT\s*/\s*DAY\s*\(\s*ABT\s*(?P<me_mt_day>[\d.]+)\s*MT\s*FOR\s*M\s*/\s*E\s*"
    r"\+\s*ABT\s*(?P<ae_mt_day>[\d.]+)\s*MT\s*FOR\s*A\s*/\s*E\s*\)",
    re.IGNORECASE,
)

_INSTRUCTION_RE_B = re.compile(
    r"INSTRUCTED\s*CP\s*SPEED\s*:\s*(?P<speed_kn>[\d.]+)\s*KTS?"
    r".*?ME\s*CONSUMPTION\s*:\s*(?P<me_mt_day>[\d.]+)\s*MT\s*/\s*DAY"
    r".*?AE\s*CONSUMPTION\s*:\s*(?P<ae_mt_day>[\d.]+)\s*MT\s*/\s*DAY",
    re.IGNORECASE | re.DOTALL,
)

_INSTRUCTION_RE_C = re.compile(
    r"INSTRUCTED\s*CP\s*(?:ECO\s*)?SPEED\s*[:\-]\s*(?P<speed_kn>[\d.]+)\s*K(?:TS|NOTS)?"
    r".*?VLSFO\s*CONSUMPTION\s*[:\-]\s*(?P<vlsfo_mt_day>[\d.]+)\s*MT"
    r".*?\(\s*ME\s*\+\s*AE\s*\)"
    r".*?LSMGO\s*(?:CONSUMPTION\s*)?[:\-]?\s*(?P<go_mt_day>[\d.]+)\s*MT",
    re.IGNORECASE | re.DOTALL,
)

_INSTRUCTION_RE_D = re.compile(
    r"(?:(?P<condition>LADEN|BALLAST)\s*\n)?"
    r"INSTRUCTED\s*CP\s*SPEED\s*[–:\-]\s*(?P<speed_kn>[\d.]+)\s*KTS?\s*,?\s*"
    r"ME\s*CONSUMPTION\s*[–:\-]\s*(?P<me_mt_day>[\d.]+)\s*MT\s*,?\s*"
    r"AE\s*CONSUMPTION\s*[–:\-]\s*(?P<ae_mt_day>[\d.]+)\s*MT",
    re.IGNORECASE,
)

_INSTRUCTION_RE_E = re.compile(
    r"(?P<condition>LADEN|BALLAST)\s*//\s*(?P<speed_kn>[\d.]+)\s*KNOTS?\s*//\s*"
    r"(?P<total_mt_day>[\d.]+)\s*MT\s*/\s*DAY\s*\(\s*ME\s*\+\s*AE\s*\)",
    re.IGNORECASE,
)

_CONDITION_NORMALIZE = {"laden": "Laden", "ballast": "Ballast"}


def _condition_or_none(raw):
    if not raw:
        return None
    return _CONDITION_NORMALIZE.get(raw.lower(), raw.title())


def parse_cp_remarks(remarks_text):
    """Returns a list of parsed instructions found in one remarks field —
    usually 0 or 1, occasionally 2 (Format A only, one per loading
    condition). Each entry:
        {
            "loading_condition": "Laden" | "Ballast" | None,
            "speed_kn": float,
            "total_mt_day": float,       # FO-side total (see per-format notes)
            "me_mt_day": float | None,   # None when the format doesn't split ME/AE
            "ae_mt_day": float | None,
            "go_mt_day": float | None,   # a REAL GO figure — only Format C gives one
            "raw_line": <the matched substring, for traceability>,
        }
    "loading_condition": None means the text itself doesn't name a
    condition (Formats B/C) — applies regardless of the report's own
    condition (see pick_instruction_for_condition).

    An empty list means the remarks text didn't match any of the 5 known
    formats — NOT that the day has no instruction; a human should glance at
    the raw text before assuming this day is genuinely uncovered (see this
    module's docstring for real examples of genuinely-no-instruction text)."""
    if not remarks_text or not str(remarks_text).strip():
        return []
    text = str(remarks_text)
    out = []

    for m in _INSTRUCTION_RE_A.finditer(text):
        try:
            out.append({
                "loading_condition": _condition_or_none(m.group("condition")),
                "speed_kn": float(m.group("speed_kn")),
                "total_mt_day": float(m.group("total_mt_day")),
                "me_mt_day": float(m.group("me_mt_day")),
                "ae_mt_day": float(m.group("ae_mt_day")),
                "go_mt_day": None,
                "raw_line": m.group(0).strip(),
            })
        except (TypeError, ValueError):
            continue

    for m in _INSTRUCTION_RE_B.finditer(text):
        try:
            me = float(m.group("me_mt_day"))
            ae = float(m.group("ae_mt_day"))
            out.append({
                "loading_condition": None,
                "speed_kn": float(m.group("speed_kn")),
                "total_mt_day": me + ae,
                "me_mt_day": me,
                "ae_mt_day": ae,
                "go_mt_day": None,
                "raw_line": m.group(0).strip(),
            })
        except (TypeError, ValueError):
            continue

    for m in _INSTRUCTION_RE_C.finditer(text):
        try:
            out.append({
                "loading_condition": None,
                "speed_kn": float(m.group("speed_kn")),
                "total_mt_day": float(m.group("vlsfo_mt_day")),
                "me_mt_day": None,
                "ae_mt_day": None,
                "go_mt_day": float(m.group("go_mt_day")),
                "raw_line": m.group(0).strip(),
            })
        except (TypeError, ValueError):
            continue

    for m in _INSTRUCTION_RE_D.finditer(text):
        try:
            me = float(m.group("me_mt_day"))
            ae = float(m.group("ae_mt_day"))
            out.append({
                "loading_condition": _condition_or_none(m.group("condition")),
                "speed_kn": float(m.group("speed_kn")),
                "total_mt_day": me + ae,
                "me_mt_day": me,
                "ae_mt_day": ae,
                "go_mt_day": None,
                "raw_line": m.group(0).strip(),
            })
        except (TypeError, ValueError):
            continue

    for m in _INSTRUCTION_RE_E.finditer(text):
        try:
            out.append({
                "loading_condition": _condition_or_none(m.group("condition")),
                "speed_kn": float(m.group("speed_kn")),
                "total_mt_day": float(m.group("total_mt_day")),
                "me_mt_day": None,
                "ae_mt_day": None,
                "go_mt_day": None,
                "raw_line": m.group(0).strip(),
            })
        except (TypeError, ValueError):
            continue

    return out


def pick_instruction_for_condition(parsed_instructions, loading_condition):
    """Given the list parse_cp_remarks() returned and the report's OWN
    loading_condition (from the same row — already tracked independently),
    return the matching instruction dict, or None if remarks didn't cover
    that condition (including when remarks parsed to nothing at all).

    An instruction with loading_condition=None (Formats B/C, which never
    name a condition in the text) applies regardless of the target
    condition — it's a wildcard."""
    if not loading_condition or not parsed_instructions:
        return None
    target = str(loading_condition).strip().lower()
    for instr in parsed_instructions:
        if instr["loading_condition"] is None or instr["loading_condition"].lower() == target:
            return instr
    return None
