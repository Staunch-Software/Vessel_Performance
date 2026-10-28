"""
Biofuel Calc — CRUD over the biofuel_bunker_stems ledger, a 1:1 rebuild of
the client's "Biofuel_Calc" worksheet (Unified_Emissions_2026_v6 -
Final.xlsx). See backend/emission/biofuel_calculator.py's docstring for the
cell-by-cell formula citations this module's _row_with_calc() reproduces.

BDN #/Date/Port/Base Fuel/Total Qty should come from a real bunker delivery
already scraped into mariapps_bunker_reports wherever one exists, rather
than be retyped by hand — see /bunker-candidates below. That table has no
concept of "this delivery was a biofuel blend" at all (the MariApps grid
itself doesn't expose blend %, so it can't be scraped), which is the only
reason this ledger's biofuel-specific fields stay manual entry. Only
GCL SABARMATI has any scraped bunker-report data fleet-wide at the time of
writing (same real gap noted elsewhere in this codebase, e.g.
expander.py's BDN Ref FIFO windows) — every other vessel still falls back
to fully manual entry until more vessels' bunker reports are scraped.
"""
import logging
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from pydantic import BaseModel

from backend.database import SessionLocal
from backend.models import BiofuelBunkerStem, BiofuelPoS, Vessel, MariAppsBunkerReport
from backend.emission.biofuel_calculator import (
    stem_calc, weighted_summary, CF_BASE, pos_wtw, POS_WTW_ADDER,
)

# Float tolerance when comparing allocated mass against a PoS / stem quantity.
_QTY_TOL = 0.001

log = logging.getLogger(__name__)
router = APIRouter(prefix="/biofuel", tags=["biofuel"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class StemPayload(BaseModel):
    vessel_imo: str
    bunker_report_id: Optional[int] = None
    bdn_number: Optional[str] = None
    delivery_date: Optional[date] = None
    port: Optional[str] = None
    base_fuel_grade: str
    biofuel_type: str = "FAME Biodiesel"
    input_basis: str = "Mass%"
    bio_pct: float = 0
    rho_base: Optional[float] = None
    rho_bio: Optional[float] = None
    quantity_mt: float
    pos_id: Optional[int] = None
    pos_allocated_mt: Optional[float] = None


class PoSPayload(BaseModel):
    pos_reference: str
    supplier: Optional[str] = None
    biofuel_type: str = "FAME Biodiesel"
    emission_intensity: float
    quantity_mt: float
    notes: Optional[str] = None


def _validate(payload: StemPayload):
    if payload.base_fuel_grade not in CF_BASE:
        raise HTTPException(status_code=400, detail=f"base_fuel_grade must be one of {list(CF_BASE)}.")
    if payload.input_basis not in ("Vol%", "Mass%"):
        raise HTTPException(status_code=400, detail="input_basis must be 'Vol%' or 'Mass%'.")
    if payload.input_basis == "Vol%" and (payload.rho_base is None or payload.rho_bio is None):
        raise HTTPException(status_code=400, detail="rho_base and rho_bio are required when input_basis is 'Vol%'.")
    if not (0 <= payload.bio_pct <= 100):
        raise HTTPException(status_code=400, detail="bio_pct must be between 0 and 100.")
    if payload.quantity_mt <= 0:
        raise HTTPException(status_code=400, detail="quantity_mt must be positive.")


def _row_with_calc(row: BiofuelBunkerStem, pos: Optional[BiofuelPoS] = None):
    pw = pos_wtw(pos.biofuel_type, pos.emission_intensity) if pos else None
    calc = stem_calc(row.base_fuel_grade, row.input_basis, row.bio_pct, row.rho_base, row.rho_bio,
                     row.quantity_mt, pw, row.pos_allocated_mt)
    return {
        "id": row.id, "vessel_imo": row.vessel_imo, "bunker_report_id": row.bunker_report_id,
        "bdn_number": row.bdn_number,
        "delivery_date": row.delivery_date.isoformat() if row.delivery_date else None,
        "port": row.port, "base_fuel_grade": row.base_fuel_grade, "biofuel_type": row.biofuel_type,
        "input_basis": row.input_basis, "bio_pct": row.bio_pct,
        "rho_base": row.rho_base, "rho_bio": row.rho_bio, "quantity_mt": row.quantity_mt,
        "pos_id": row.pos_id, "pos_allocated_mt": row.pos_allocated_mt,
        "pos_reference": pos.pos_reference if pos else None,
        **calc,
    }


def _pos_for(db: Session, rows):
    ids = {r.pos_id for r in rows if r.pos_id is not None}
    if not ids:
        return {}
    return {p.id: p for p in db.query(BiofuelPoS).filter(BiofuelPoS.id.in_(ids)).all()}


def _allocated_totals(db: Session):
    """{pos_id: (allocated_mt, stem_count)} across every vessel's stems."""
    q = (
        db.query(BiofuelBunkerStem.pos_id, func.coalesce(func.sum(BiofuelBunkerStem.pos_allocated_mt), 0.0),
                 func.count(BiofuelBunkerStem.id))
        .filter(BiofuelBunkerStem.pos_id.isnot(None))
        .group_by(BiofuelBunkerStem.pos_id)
    )
    return {pid: (alloc, n) for pid, alloc, n in q.all()}


def _pos_row(p: BiofuelPoS, allocated: float = 0.0, stem_count: int = 0):
    return {
        "id": p.id, "pos_reference": p.pos_reference, "supplier": p.supplier,
        "biofuel_type": p.biofuel_type, "emission_intensity": p.emission_intensity,
        "wtw": round(pos_wtw(p.biofuel_type, p.emission_intensity), 4),
        "quantity_mt": p.quantity_mt, "notes": p.notes,
        "allocated_mt": round(allocated, 3), "remaining_mt": round(p.quantity_mt - allocated, 3),
        "stem_count": stem_count,
    }


def _resolve_pos_link(payload: StemPayload, db: Session, stem_id: Optional[int] = None) -> StemPayload:
    """Validate the stem's PoS link: type match, allocation within this stem's
    own bio portion, and total allocations across all stems within the PoS
    quantity (so one PoS can serve several stems without double counting).
    An omitted allocation defaults to the stem's whole bio portion."""
    if payload.pos_id is None:
        return payload.model_copy(update={"pos_allocated_mt": None})
    pos = db.query(BiofuelPoS).filter(BiofuelPoS.id == payload.pos_id).first()
    if not pos:
        raise HTTPException(status_code=404, detail=f"No PoS record with id {payload.pos_id}.")
    if pos.biofuel_type != payload.biofuel_type:
        raise HTTPException(status_code=400, detail=f"PoS {pos.pos_reference} is {pos.biofuel_type}; the stem's biofuel type is {payload.biofuel_type}.")
    bio_mt = stem_calc(payload.base_fuel_grade, payload.input_basis, payload.bio_pct, payload.rho_base,
                       payload.rho_bio, payload.quantity_mt)["bio_portion_mt"]
    if not bio_mt:
        raise HTTPException(status_code=400, detail="This stem has no biofuel portion to allocate a PoS to (Bio % is 0).")
    alloc = payload.pos_allocated_mt if payload.pos_allocated_mt is not None else round(bio_mt, 3)
    if alloc <= 0:
        raise HTTPException(status_code=400, detail="pos_allocated_mt must be positive.")
    if alloc > bio_mt + _QTY_TOL:
        raise HTTPException(status_code=400, detail=f"Allocated {alloc} mt exceeds this stem's biofuel portion ({round(bio_mt, 3)} mt).")
    q = db.query(func.coalesce(func.sum(BiofuelBunkerStem.pos_allocated_mt), 0.0)).filter(BiofuelBunkerStem.pos_id == pos.id)
    if stem_id is not None:
        q = q.filter(BiofuelBunkerStem.id != stem_id)
    others = q.scalar() or 0.0
    if others + alloc > pos.quantity_mt + _QTY_TOL:
        raise HTTPException(
            status_code=400,
            detail=f"PoS {pos.pos_reference} covers {pos.quantity_mt} mt and {round(others, 3)} mt is already allocated to other stems — only {round(pos.quantity_mt - others, 3)} mt remains.",
        )
    return payload.model_copy(update={"pos_allocated_mt": alloc})


# imo_fuel_grade on a scraped bunker report is free text from the MariApps
# grid — only map the values that are already unambiguous IMO DCS grades;
# anything else (e.g. a bare "VLSFO", which per RefConstants needs the
# ISO 8217 sub-grade to classify as HFO vs LFO) is left for the user to pick,
# not guessed at.
_GRADE_MAP = {"HFO": "HFO", "LFO": "LFO", "MDO": "MDO", "MGO": "MDO"}


def _parse_bunker_date(s):
    if not s:
        return None
    for fmt in ("%d-%b-%Y %H:%M", "%d-%b-%Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


@router.get("/vessels")
def list_biofuel_vessels(db: Session = Depends(get_db)):
    """Vessels that already have at least one stem logged — same convention
    as GET /bunker-report/vessels."""
    imos = [r[0] for r in db.query(BiofuelBunkerStem.vessel_imo).distinct().all()]
    if not imos:
        return []
    vessels = db.query(Vessel).filter(Vessel.imo_number.in_(imos)).order_by(Vessel.vessel_name).all()
    return [{"imo_number": v.imo_number, "vessel_name": v.vessel_name} for v in vessels]


@router.get("/{imo}/bunker-candidates")
def list_bunker_candidates(imo: str, db: Session = Depends(get_db)):
    """Real scraped 'Bunkering' deliveries for this vessel that aren't
    already linked to a biofuel stem — the source list for Add Stem's
    "From Bunker Report" picker. Empty for every vessel except the handful
    MariApps bunker-report scraping actually covers (see module docstring)
    — the frontend falls back to manual entry when this is empty."""
    linked_ids = {
        r[0] for r in db.query(BiofuelBunkerStem.bunker_report_id)
        .filter(BiofuelBunkerStem.bunker_report_id.isnot(None)).all()
    }
    rows = (
        db.query(MariAppsBunkerReport)
        .filter(MariAppsBunkerReport.vessel_imo == imo, MariAppsBunkerReport.transaction_type == "Bunkering")
        .order_by(MariAppsBunkerReport.id.asc())
        .all()
    )
    out = []
    for r in rows:
        if r.id in linked_ids:
            continue
        parsed_date = _parse_bunker_date(r.begin_of_bunkering)
        out.append({
            "bunker_report_id": r.id,
            "bdn_number": r.bdn_reference_no,
            "delivery_date": parsed_date.isoformat() if parsed_date else None,
            "port": r.port,
            "imo_fuel_grade": r.imo_fuel_grade,
            "base_fuel_grade": _GRADE_MAP.get((r.imo_fuel_grade or "").strip().upper()),
            "quantity_mt": r.quantity_mt,
            "supplier_company": r.supplier_company,
        })
    return out


@router.get("/{imo}/stems")
def list_stems(imo: str, db: Session = Depends(get_db)):
    rows = (
        db.query(BiofuelBunkerStem)
        .filter(BiofuelBunkerStem.vessel_imo == imo)
        .order_by(BiofuelBunkerStem.delivery_date.desc().nullslast(), BiofuelBunkerStem.id.desc())
        .all()
    )
    pos_map = _pos_for(db, rows)
    stems = [_row_with_calc(r, pos_map.get(r.pos_id)) for r in rows]
    summary = weighted_summary([
        {"quantity_mt": s["quantity_mt"], "cf_blend": s["cf_blend"], "wtw_blend": s["wtw_blend"],
         "fossil_portion_mt": s["fossil_portion_mt"], "bio_portion_mt": s["bio_portion_mt"]}
        for s in stems
    ])
    return {"vessel_imo": imo, "stems": stems, "summary": {"stem_count": len(stems), **summary}}


def _apply_bunker_report_link(payload: StemPayload, db: Session):
    """When bunker_report_id is set, BDN #/Date/Port/Total Qty are copied
    from that real delivery — the payload's own values for those fields are
    ignored (the frontend sends them read-only/disabled anyway, but this is
    the actual source of truth, not trust-the-client)."""
    if payload.bunker_report_id is None:
        return payload
    report = db.query(MariAppsBunkerReport).filter(MariAppsBunkerReport.id == payload.bunker_report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail=f"No bunker report with id {payload.bunker_report_id}.")
    if report.vessel_imo != payload.vessel_imo:
        raise HTTPException(status_code=400, detail="That bunker report belongs to a different vessel.")
    data = payload.model_dump()
    data["bdn_number"] = report.bdn_reference_no
    data["delivery_date"] = _parse_bunker_date(report.begin_of_bunkering)
    data["port"] = report.port
    data["quantity_mt"] = report.quantity_mt or payload.quantity_mt
    return StemPayload(**data)


@router.post("/stems")
def create_stem(payload: StemPayload, db: Session = Depends(get_db)):
    if not db.query(Vessel).filter(Vessel.imo_number == payload.vessel_imo).first():
        raise HTTPException(status_code=404, detail=f"No vessel with IMO {payload.vessel_imo}.")
    payload = _apply_bunker_report_link(payload, db)
    _validate(payload)
    payload = _resolve_pos_link(payload, db)
    if payload.bunker_report_id is not None:
        existing = db.query(BiofuelBunkerStem).filter(BiofuelBunkerStem.bunker_report_id == payload.bunker_report_id).first()
        if existing:
            raise HTTPException(status_code=409, detail="That bunker report is already linked to another biofuel stem.")
    row = BiofuelBunkerStem(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return _row_with_calc(row, _pos_for(db, [row]).get(row.pos_id))


@router.patch("/stems/{stem_id}")
def update_stem(stem_id: int, payload: StemPayload, db: Session = Depends(get_db)):
    payload = _apply_bunker_report_link(payload, db)
    _validate(payload)
    row = db.query(BiofuelBunkerStem).filter(BiofuelBunkerStem.id == stem_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"No biofuel stem with id {stem_id}.")
    payload = _resolve_pos_link(payload, db, stem_id=stem_id)
    for k, v in payload.model_dump().items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return _row_with_calc(row, _pos_for(db, [row]).get(row.pos_id))


# ── Proof of Sustainability records ────────────────────────────────────────
# Held separately from stems and shared across vessels: one consignment's PoS
# can back several stems via BiofuelBunkerStem.pos_id/pos_allocated_mt.

def _validate_pos(payload: PoSPayload):
    if not payload.pos_reference.strip():
        raise HTTPException(status_code=400, detail="pos_reference is required.")
    if payload.biofuel_type not in POS_WTW_ADDER:
        raise HTTPException(status_code=400, detail=f"biofuel_type must be one of {list(POS_WTW_ADDER)}.")
    if payload.quantity_mt <= 0:
        raise HTTPException(status_code=400, detail="quantity_mt must be positive.")


@router.get("/pos")
def list_pos(db: Session = Depends(get_db)):
    totals = _allocated_totals(db)
    rows = db.query(BiofuelPoS).order_by(BiofuelPoS.id.desc()).all()
    return [_pos_row(p, *totals.get(p.id, (0.0, 0))) for p in rows]


@router.post("/pos")
def create_pos(payload: PoSPayload, db: Session = Depends(get_db)):
    _validate_pos(payload)
    row = BiofuelPoS(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return _pos_row(row)


@router.patch("/pos/{pos_id}")
def update_pos(pos_id: int, payload: PoSPayload, db: Session = Depends(get_db)):
    _validate_pos(payload)
    row = db.query(BiofuelPoS).filter(BiofuelPoS.id == pos_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"No PoS record with id {pos_id}.")
    allocated, n = _allocated_totals(db).get(pos_id, (0.0, 0))
    if payload.quantity_mt < allocated - _QTY_TOL:
        raise HTTPException(status_code=400, detail=f"{round(allocated, 3)} mt is already allocated to stems — quantity cannot go below that.")
    if payload.biofuel_type != row.biofuel_type and n:
        raise HTTPException(status_code=400, detail="Biofuel type can't change while stems are linked to this PoS.")
    for k, v in payload.model_dump().items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return _pos_row(row, allocated, n)


@router.delete("/pos/{pos_id}")
def delete_pos(pos_id: int, db: Session = Depends(get_db)):
    row = db.query(BiofuelPoS).filter(BiofuelPoS.id == pos_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"No PoS record with id {pos_id}.")
    _, n = _allocated_totals(db).get(pos_id, (0.0, 0))
    if n:
        raise HTTPException(status_code=409, detail=f"{n} stem(s) are linked to this PoS — unlink them first.")
    db.delete(row)
    db.commit()
    return {"deleted": pos_id}


@router.delete("/stems/{stem_id}")
def delete_stem(stem_id: int, db: Session = Depends(get_db)):
    row = db.query(BiofuelBunkerStem).filter(BiofuelBunkerStem.id == stem_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"No biofuel stem with id {stem_id}.")
    db.delete(row)
    db.commit()
    return {"deleted": stem_id}
