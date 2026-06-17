"""
expanded_routes.py
------------------
API endpoints for the two expanded flat tables:
  GET /expanded/columns          - column metadata (for column picker)
  GET /expanded/mariapps         - query expanded_mariapps_data
  GET /expanded/wni              - query expanded_wni_data
  PATCH /expanded/columns/{id}   - toggle is_active on a column
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional
from datetime import date

from backend.database import SessionLocal
from backend.models import ExpandedColumnMetadata

router = APIRouter(prefix="/expanded")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Column metadata ──────────────────────────────────────────────────────────

@router.get("/columns")
def get_columns(
    source: str = Query(..., description="'wni' or 'mari_apps'"),
    db: Session = Depends(get_db),
):
    """Return all column metadata for a given source, ordered by sort_order."""
    rows = (
        db.query(ExpandedColumnMetadata)
        .filter(ExpandedColumnMetadata.source == source)
        .order_by(ExpandedColumnMetadata.sort_order)
        .all()
    )
    return [
        {
            "id":           r.id,
            "db_column":    r.db_column,
            "display_name": r.display_name,
            "category":     r.category,
            "unit":         r.unit,
            "description":  r.description,
            "is_active":    r.is_active,
            "is_identity":  r.is_identity,
            "performance":  getattr(r, "performance", False) or False,
            "sort_order":   r.sort_order,
        }
        for r in rows
    ]


@router.patch("/columns/{col_id}")
def toggle_column(col_id: int, body: dict, db: Session = Depends(get_db)):
    """Toggle is_active for a column (only pink/inactive ones can be toggled)."""
    col = db.query(ExpandedColumnMetadata).filter(ExpandedColumnMetadata.id == col_id).first()
    if not col:
        raise HTTPException(status_code=404, detail="Column not found")
    if col.is_identity:
        raise HTTPException(status_code=400, detail="Identity columns cannot be toggled")
    col.is_active = bool(body.get("is_active", col.is_active))
    db.commit()
    return {"id": col.id, "is_active": col.is_active}


# ── Data queries ─────────────────────────────────────────────────────────────

def _build_query(
    table: str,
    date_col: str,
    vessel_imo: Optional[str],
    from_date: Optional[str],
    to_date: Optional[str],
    voyage_col: Optional[str],
    voyage_no: Optional[str],
    columns: list,
    loading_cond: Optional[str] = None,
    loading_col:  str = "loading_condition",
) -> tuple:
    """Build a parameterised SELECT query."""
    col_sql = ", ".join(f'"{c}"' for c in columns)
    where_clauses = []
    params = {}

    if vessel_imo:
        where_clauses.append("vessel_imo = :vessel_imo")
        params["vessel_imo"] = vessel_imo
    if from_date:
        where_clauses.append(f"{date_col} >= :from_date")
        params["from_date"] = from_date
    if to_date:
        where_clauses.append(f"{date_col} <= :to_date")
        params["to_date"] = to_date
    if voyage_no and voyage_col:
        # Use LIKE so "AM KIRTI V 36/02" matches "AM KIRTI V 36/02/01" etc.
        where_clauses.append(f'"{voyage_col}" LIKE :voyage_no')
        params["voyage_no"] = f"{str(voyage_no)}%"
    if loading_cond and loading_cond.lower() != "all":
        where_clauses.append(f'"{loading_col}" ILIKE :loading_cond')
        params["loading_cond"] = loading_cond

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    sql = f"SELECT {col_sql} FROM {table} {where_sql} ORDER BY {date_col} DESC LIMIT 2000"
    return sql, params


def _rows_to_dicts(result) -> List[dict]:
    keys = list(result.keys())
    return [dict(zip(keys, row)) for row in result]


@router.get("/mariapps")
def query_mariapps(
    vessel_imo:   Optional[str] = None,
    from_date:    Optional[str] = None,
    to_date:      Optional[str] = None,
    voyage_no:    Optional[str] = None,
    loading_cond: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Query expanded_mariapps_data with optional filters."""
    try:
        # Get active + identity columns
        meta = (
            db.query(ExpandedColumnMetadata)
            .filter(
                ExpandedColumnMetadata.source == "mari_apps",
                (ExpandedColumnMetadata.is_active == True) |
                (ExpandedColumnMetadata.is_identity == True),
            )
            .order_by(ExpandedColumnMetadata.sort_order)
            .all()
        )
        if not meta:
            return []

        cols = [m.db_column for m in meta]
        sql, params = _build_query(
            table="expanded_mariapps_data",
            date_col="log_date",
            vessel_imo=vessel_imo,
            from_date=from_date,
            to_date=to_date,
            voyage_col="log_number",   # log_number is the voyage/leg identifier in expanded_mariapps_data
            voyage_no=voyage_no,
            columns=cols,
            loading_cond=loading_cond,
            loading_col="loading_condition",
        )
        result = db.execute(text(sql), params)
        return _rows_to_dicts(result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/wni")
def query_wni(
    vessel_imo:   Optional[str] = None,
    from_date:    Optional[str] = None,
    to_date:      Optional[str] = None,
    voyage_no:    Optional[str] = None,
    loading_cond: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Query expanded_wni_data with optional filters."""
    try:
        # Get actual columns in expanded_wni_data to guard against stale metadata
        actual_cols = {
            r[0] for r in db.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'expanded_wni_data'"
            )).fetchall()
        }

        meta = (
            db.query(ExpandedColumnMetadata)
            .filter(
                ExpandedColumnMetadata.source == "wni",
                (ExpandedColumnMetadata.is_active == True) |
                (ExpandedColumnMetadata.is_identity == True),
            )
            .order_by(ExpandedColumnMetadata.sort_order)
            .all()
        )
        if not meta:
            return []

        # Only select columns that actually exist in the table
        cols = [m.db_column for m in meta if m.db_column in actual_cols]
        sql, params = _build_query(
            table="expanded_wni_data",
            date_col="date",
            vessel_imo=vessel_imo,
            from_date=from_date,
            to_date=to_date,
            voyage_col="voyage_no",
            voyage_no=voyage_no,
            columns=cols,
            loading_cond=loading_cond,
            loading_col="loading_condition",
        )
        result = db.execute(text(sql), params)
        return _rows_to_dicts(result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
