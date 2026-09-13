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

FORMAT — confirmed from real remarks text (two examples, AM TARANG):
    "LADEN ABT 11.5 KNOTS ON ABT IFO 30.5 MT/DAY (ABT 26.9 MT FOR M/E + ABT 3.6 MT FOR A/E)"
    "BALLAST ABT 14.8 KNOTS ON ABT IFO 44.0 MT/DAY(ABT 40.4MT FOR M/E+ABT 3.6 MT FOR A/E)"
A single remarks field can hold ONE line (the condition currently sailing)
or TWO lines, one per loading condition — seen on a report logged the day
the vessel's condition/instruction was being restated or was about to
change. The regex below tolerates the punctuation/spacing drift already
observed between these two real examples (missing spaces around "MT"/"+"),
but this is pattern-matched free text a human typed, not a structured
field — treat an unparsed line as a genuine "no override for this day"
case, not an error, and don't assume this regex covers every master's
phrasing without sampling more real remarks first (see module docstring
in expander.py's _mariapps_remarks_field for the same caveat).
"""

import re

_INSTRUCTION_RE = re.compile(
    r"(?P<condition>LADEN|BALLAST)\s*ABT\s*(?P<speed_kn>[\d.]+)\s*KNOTS?\s*ON\s*ABT\s*IFO\s*"
    r"(?P<total_mt_day>[\d.]+)\s*MT\s*/\s*DAY\s*\(\s*ABT\s*(?P<me_mt_day>[\d.]+)\s*MT\s*FOR\s*M\s*/\s*E\s*"
    r"\+\s*ABT\s*(?P<ae_mt_day>[\d.]+)\s*MT\s*FOR\s*A\s*/\s*E\s*\)",
    re.IGNORECASE,
)

_CONDITION_NORMALIZE = {"laden": "Laden", "ballast": "Ballast"}


def parse_cp_remarks(remarks_text):
    """Returns a list of parsed instructions found in one remarks field —
    usually 0 or 1, sometimes 2 (one per loading condition). Each entry:
        {
            "loading_condition": "Laden" | "Ballast",
            "speed_kn": float,
            "total_mt_day": float,
            "me_mt_day": float,
            "ae_mt_day": float,
            "raw_line": <the matched substring, for traceability>,
        }
    An empty list means the remarks text didn't match the known format —
    NOT that the day has no instruction; a human should glance at the raw
    text before assuming this day is genuinely uncovered by any CP note."""
    if not remarks_text or not str(remarks_text).strip():
        return []
    out = []
    for m in _INSTRUCTION_RE.finditer(str(remarks_text)):
        try:
            out.append({
                "loading_condition": _CONDITION_NORMALIZE.get(m.group("condition").lower(), m.group("condition").title()),
                "speed_kn": float(m.group("speed_kn")),
                "total_mt_day": float(m.group("total_mt_day")),
                "me_mt_day": float(m.group("me_mt_day")),
                "ae_mt_day": float(m.group("ae_mt_day")),
                "raw_line": m.group(0).strip(),
            })
        except (TypeError, ValueError):
            continue
    return out


def pick_instruction_for_condition(parsed_instructions, loading_condition):
    """Given the list parse_cp_remarks() returned and the report's OWN
    loading_condition (from the same row — already tracked independently),
    return the matching instruction dict, or None if remarks didn't cover
    that condition (including when remarks parsed to nothing at all)."""
    if not loading_condition or not parsed_instructions:
        return None
    target = str(loading_condition).strip().lower()
    for instr in parsed_instructions:
        if instr["loading_condition"].lower() == target:
            return instr
    return None
