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
from sqlalchemy import text, func
from typing import List, Optional
from datetime import date

from backend.database import SessionLocal
from backend.models import ExpandedColumnMetadata, VesselColumnOrder

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
    vessel_imo: Optional[str] = Query(None, description="If set and this vessel has its own saved order for some columns, those take precedence over the global order for those columns."),
    db: Session = Depends(get_db),
):
    """Return all column metadata for a given source, ordered by (in precedence order):
    1. This vessel's own saved order (vessel_column_order), for whichever columns it covers
    2. The global user-defined order (expanded_column_metadata.user_sort_order)
    3. The default sort_order
    """
    if source == 'Wartsila FOS':
        source = 'wni'

    rows = (
        db.query(ExpandedColumnMetadata)
        .filter(ExpandedColumnMetadata.source == source)
        .all()
    )

    vessel_positions = {}
    if vessel_imo:
        vrows = (
            db.query(VesselColumnOrder)
            .filter(VesselColumnOrder.source == source, VesselColumnOrder.vessel_imo == vessel_imo)
            .all()
        )
        vessel_positions = {r.db_column: r.position for r in vrows}

    if vessel_positions:
        # This vessel has its own order for SOME columns — use those positions,
        # falling back to the global position (shifted after them) for every
        # other column so the two don't collide.
        fallback = len(vessel_positions)
        def sort_key(r):
            if r.db_column in vessel_positions:
                return vessel_positions[r.db_column]
            return fallback + (r.user_sort_order if r.user_sort_order is not None else r.sort_order)
        rows.sort(key=sort_key)
    else:
        rows.sort(key=lambda r: r.user_sort_order if r.user_sort_order is not None else r.sort_order)

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
            "emission":     getattr(r, "emission", False) or False,
            "sort_order":   r.sort_order,
            # Reflects whichever order actually governed this response (vessel-specific
            # when present for this column, else global).
            "user_sort_order": vessel_positions.get(r.db_column, r.user_sort_order),
            "emission_sort_order": r.emission_sort_order,
        }
        for r in rows
    ]


@router.put("/columns/reorder")
def reorder_columns(body: dict, db: Session = Depends(get_db)):
    """
    Persist a user-defined column order for a source.
    Body: { "source": "mari_apps" | "wni", "order": ["db_col_1", ...],
            "target"?: "primary" | "emission", "vessel_imo"?: "1234567" }

    target="emission" writes emission_sort_order (always global — the
    Emission picker bucket's own arrangement; vessel_imo is ignored for this
    target, since every column there is a duplicate listing the real table
    never groups by "Emission" anyway).

    target="primary" (default) is the normal category reorder:
    - vessel_imo given ("This Vessel" scope): saves to vessel_column_order for
      THAT VESSEL ONLY — every other vessel is unaffected.
    - vessel_imo omitted ("Global" scope): saves to the shared
      expanded_column_metadata.user_sort_order AND deletes any
      vessel_column_order rows for these SAME columns across every vessel —
      so a Global edit reaches into and overrides even a vessel that already
      customized this exact category, while that vessel's customization for
      every column NOT included in this save is left untouched.
    """
    source     = body.get("source")
    order      = body.get("order")
    target     = body.get("target", "primary")
    vessel_imo = body.get("vessel_imo")
    if source not in ("mari_apps", "wni"):
        raise HTTPException(status_code=400, detail="source must be 'mari_apps' or 'wni'")
    if not isinstance(order, list) or not order:
        raise HTTPException(status_code=400, detail="order must be a non-empty list of db_column names")
    if target not in ("primary", "emission"):
        raise HTTPException(status_code=400, detail="target must be 'primary' or 'emission'")

    if target == "emission":
        rows = db.query(ExpandedColumnMetadata).filter(ExpandedColumnMetadata.source == source).all()
        by_col = {r.db_column: r for r in rows}
        pos = 0
        for db_col in order:
            r = by_col.get(db_col)
            if r is not None:
                r.emission_sort_order = pos
                pos += 1
        db.commit()
        return {"source": source, "target": "emission", "updated": pos}

    if vessel_imo:
        valid_cols = {
            r.db_column for r in db.query(ExpandedColumnMetadata.db_column)
            .filter(ExpandedColumnMetadata.source == source).all()
        }
        existing = {
            r.db_column: r for r in db.query(VesselColumnOrder)
            .filter(VesselColumnOrder.vessel_imo == vessel_imo, VesselColumnOrder.source == source)
            .all()
        }
        pos = 0
        for db_col in order:
            if db_col not in valid_cols:
                continue
            if db_col in existing:
                existing[db_col].position = pos
            else:
                db.add(VesselColumnOrder(vessel_imo=vessel_imo, source=source, db_column=db_col, position=pos))
            pos += 1
        db.commit()
        return {"source": source, "target": "primary", "vessel_imo": vessel_imo, "updated": pos}

    # Global: update the shared order AND clear any per-vessel override for
    # these exact columns, across every vessel — a Global edit to a category
    # reaches through even a vessel that already customized it.
    rows = db.query(ExpandedColumnMetadata).filter(ExpandedColumnMetadata.source == source).all()
    by_col = {r.db_column: r for r in rows}
    pos = 0
    for db_col in order:
        r = by_col.get(db_col)
        if r is not None:
            r.user_sort_order = pos
            pos += 1
    db.query(VesselColumnOrder).filter(
        VesselColumnOrder.source == source,
        VesselColumnOrder.db_column.in_(order),
    ).delete(synchronize_session=False)
    db.commit()
    return {"source": source, "target": "primary", "updated": pos}


@router.delete("/columns/reorder")
def reset_column_order(
    source: str = Query(...),
    columns: Optional[str] = Query(None, description="Comma-separated db_column names to reset order for (e.g. one category's columns). Omit to reset every column of this source."),
    target: str = Query("primary", description="'primary' or 'emission' — which order field to clear"),
    vessel_imo: Optional[str] = Query(None, description="With target=primary: clear only this vessel's own order (falls back to global). Omit to clear the global order."),
    db: Session = Depends(get_db),
):
    """Clear the user-defined order for a source, or just a subset of its columns
    (revert to default sort_order). Passing `columns` scopes the reset to only
    those columns — e.g. one category block — leaving every other column's
    saved order untouched."""
    if source not in ("mari_apps", "wni"):
        raise HTTPException(status_code=400, detail="source must be 'mari_apps' or 'wni'")
    if target not in ("primary", "emission"):
        raise HTTPException(status_code=400, detail="target must be 'primary' or 'emission'")

    if target == "primary" and vessel_imo:
        q = db.query(VesselColumnOrder).filter(
            VesselColumnOrder.vessel_imo == vessel_imo, VesselColumnOrder.source == source
        )
        if columns:
            col_list = [c.strip() for c in columns.split(",") if c.strip()]
            if not col_list:
                raise HTTPException(status_code=400, detail="columns, if provided, must be a non-empty comma-separated list")
            q = q.filter(VesselColumnOrder.db_column.in_(col_list))
        q.delete(synchronize_session=False)
        db.commit()
        return {"source": source, "target": "primary", "vessel_imo": vessel_imo, "reset": True, "columns": columns}

    field = ExpandedColumnMetadata.emission_sort_order if target == "emission" else ExpandedColumnMetadata.user_sort_order

    q = db.query(ExpandedColumnMetadata).filter(ExpandedColumnMetadata.source == source)
    if columns:
        col_list = [c.strip() for c in columns.split(",") if c.strip()]
        if not col_list:
            raise HTTPException(status_code=400, detail="columns, if provided, must be a non-empty comma-separated list")
        q = q.filter(ExpandedColumnMetadata.db_column.in_(col_list))

    q.update({field: None}, synchronize_session=False)
    db.commit()
    return {"source": source, "target": target, "reset": True, "columns": columns}


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
        v_imo_str = str(vessel_imo).strip()
        # Fallback for corrected AMNS IMOs across expanded tables
        if v_imo_str in ('9961609', '9521813'):
            where_clauses.append("vessel_imo IN ('9961609', '9521813')")
        elif v_imo_str in ('9942768', '9628893'):
            where_clauses.append("vessel_imo IN ('9942768', '9628893')")
        elif v_imo_str in ('9942770', '9628910'):
            where_clauses.append("vessel_imo IN ('9942770', '9628910')")
        else:
            where_clauses.append("vessel_imo = :vessel_imo")
            params["vessel_imo"] = v_imo_str
    if from_date:
        where_clauses.append(f"{date_col} >= :from_date")
        params["from_date"] = from_date
    if to_date:
        where_clauses.append(f"{date_col} <= :to_date")
        params["to_date"] = to_date
    if voyage_no and voyage_col:
        # voyage_no may be a single value or a comma-separated list (multi-select).
        # Use LIKE so "AM KIRTI V 36/02" matches "AM KIRTI V 36/02/01" etc.
        voyages = (
            voyage_no if isinstance(voyage_no, (list, tuple))
            else [v.strip() for v in str(voyage_no).split(",") if v.strip()]
        )
        like_conds = []
        for i, v in enumerate(voyages):
            key = f"voyage_no_{i}"
            like_conds.append(f'"{voyage_col}" LIKE :{key}')
            params[key] = f"{v}%"
        if like_conds:
            where_clauses.append("(" + " OR ".join(like_conds) + ")")
    if loading_cond and loading_cond.lower() != "all":
        where_clauses.append(f'"{loading_col}" ILIKE :loading_cond')
        params["loading_cond"] = loading_cond

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    # Keep the most-recent 2000 rows (inner DESC + LIMIT), but return them
    # ascending so the table reads oldest → newest top-to-bottom.
    sql = (
        f"SELECT * FROM ("
        f"SELECT {col_sql} FROM {table} {where_sql} ORDER BY {date_col} DESC LIMIT 2000"
        f") sub ORDER BY {date_col} ASC"
    )
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
            .order_by(func.coalesce(
                ExpandedColumnMetadata.user_sort_order,
                ExpandedColumnMetadata.sort_order,
            ))
            .all()
        )
        if not meta:
            return []

        # Ensure coordinate columns are available for frontend formatting
        actual_cols = {
            r[0] for r in db.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'expanded_mariapps_data'"
            )).fetchall()
        }
        cols = [m.db_column for m in meta if m.db_column in actual_cols]
        for c in [
            "VoyageMeta_latitude_lat_minutes_operational_LF",
            "VoyageMeta_latitude_lat_direction_operational_LF",
            "VoyageMeta_longitude_lon_minutes_operational_LF",
            "VoyageMeta_longitude_lon_direction_operational_LF"
        ]:
            if c in actual_cols and c not in cols:
                cols.append(c)

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


def _ensure_polar_wartsila_in_expanded(db: Session):
    """
    Ensure expanded_wni_data contains Polar Wartsila FOS records synchronized from
    noon_report_data and analysis_data. If missing or incomplete, populates them idempotently.
    """
    try:
        has_polar = db.execute(text(
            "SELECT 1 FROM expanded_wni_data WHERE vessel_imo IN ('9961609', '9521813') AND source_id = 'Wartsila FOS' LIMIT 1"
        )).first()
        if has_polar:
            return

        sync_sql = text("""
            INSERT INTO expanded_wni_data (
                raw_report_id, vessel_imo, source_id, date, event_type, voyage_no, loading_condition,
                "VoyageMeta_log_durationh_operational_LF",
                "wnix_distance_nm_reported_distance_nm",
                "wnix_m_e_fuel_consumption_vlsfo_hfo_mt",
                "wnix_a_e_fuel_consumption_vlsfo_lfo_mt",
                "wnix_total_fuel_consumption_lfo_mt",
                "VoyageMeta_to_port_operational_LF",
                "VoyageMeta_departure_port_last_leg_operational_LF",
                "Vessel_SOG_avg_operational_LF",
                "wnix_speed_reported_spd_kts",
                "VoyageMeta_latitude_operational_LF",
                "VoyageMeta_latitude_lat_minutes_operational_LF",
                "VoyageMeta_latitude_lat_direction_operational_LF",
                "VoyageMeta_longitude_operational_LF",
                "VoyageMeta_longitude_lon_minutes_operational_LF",
                "VoyageMeta_longitude_lon_direction_operational_LF"
            )
            SELECT DISTINCT ON (n.raw_report_id)
                n.raw_report_id,
                '9961609' as vessel_imo,
                'Wartsila FOS' as source_id,
                CAST(n.log_date AS DATE) as date,
                n.log_type as event_type,
                a."Voyage_No" as voyage_no,
                a."Loading_Cond" as loading_condition,
                CAST(n.log_duration AS TEXT),
                CAST(n.distance_og AS TEXT),
                CAST(a."ME_FOC_MT" AS TEXT),
                CAST(a."AE_FOC_MT" AS TEXT),
                CAST(COALESCE(a."ME_FOC_MT", 0) + COALESCE(a."AE_FOC_MT", 0) AS TEXT),
                a."To_Port",
                a."From_Port",
                CAST(a."SOG_kn" AS TEXT),
                CAST(a."SOG_kn" AS TEXT),
                CAST(n.lat_degree AS TEXT),
                CAST(n.lat_minutes AS TEXT),
                n.lat_direction,
                CAST(n.lon_degree AS TEXT),
                CAST(n.lon_minutes AS TEXT),
                n.lon_direction
            FROM noon_report_data n
            JOIN analysis_data a ON a.raw_report_id = n.raw_report_id
            WHERE n.source_id = 'Wartsila FOS' AND n.vessel_imo IN ('9961609', '9521813')
            ON CONFLICT (raw_report_id) DO UPDATE SET
                vessel_imo = '9961609',
                source_id = 'Wartsila FOS',
                date = EXCLUDED.date,
                event_type = EXCLUDED.event_type,
                voyage_no = EXCLUDED.voyage_no,
                loading_condition = EXCLUDED.loading_condition,
                "VoyageMeta_log_durationh_operational_LF" = EXCLUDED."VoyageMeta_log_durationh_operational_LF",
                "wnix_distance_nm_reported_distance_nm" = EXCLUDED."wnix_distance_nm_reported_distance_nm",
                "wnix_m_e_fuel_consumption_vlsfo_hfo_mt" = EXCLUDED."wnix_m_e_fuel_consumption_vlsfo_hfo_mt",
                "wnix_a_e_fuel_consumption_vlsfo_lfo_mt" = EXCLUDED."wnix_a_e_fuel_consumption_vlsfo_lfo_mt",
                "wnix_total_fuel_consumption_lfo_mt" = EXCLUDED."wnix_total_fuel_consumption_lfo_mt",
                "VoyageMeta_to_port_operational_LF" = EXCLUDED."VoyageMeta_to_port_operational_LF",
                "VoyageMeta_departure_port_last_leg_operational_LF" = EXCLUDED."VoyageMeta_departure_port_last_leg_operational_LF",
                "Vessel_SOG_avg_operational_LF" = EXCLUDED."Vessel_SOG_avg_operational_LF",
                "wnix_speed_reported_spd_kts" = EXCLUDED."wnix_speed_reported_spd_kts";
        """)
        db.execute(sync_sql)
        db.commit()
    except Exception as e:
        db.rollback()
        import logging
        logging.getLogger("uvicorn").warning(f"Auto-sync of Polar Wartsila expanded records: {e}")


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
        # Ensure Polar Wartsila FOS records exist in expanded_wni_data if querying Polar or all
        if not vessel_imo or str(vessel_imo).strip() in ('9961609', '9521813'):
            _ensure_polar_wartsila_in_expanded(db)

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
            .order_by(func.coalesce(
                ExpandedColumnMetadata.user_sort_order,
                ExpandedColumnMetadata.sort_order,
            ))
            .all()
        )
        if not meta:
            return []

        # Only select columns that actually exist in the table
        cols = [m.db_column for m in meta if m.db_column in actual_cols]
        for c in [
            "VoyageMeta_latitude_lat_minutes_operational_LF",
            "VoyageMeta_latitude_lat_direction_operational_LF",
            "VoyageMeta_longitude_lon_minutes_operational_LF",
            "VoyageMeta_longitude_lon_direction_operational_LF"
        ]:
            if c in actual_cols and c not in cols:
                cols.append(c)

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
