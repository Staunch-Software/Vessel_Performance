# ============================================================
# COLUMN CONFIGURATOR ROUTES  (admin-only "Configure Columns" page)
# ============================================================
# GET  /api/v1/category-order                          — "All" mode category order
# PUT  /api/v1/category-order                           — [Admin] set category order
# GET  /api/v1/calculation-categories                   — list calc categories
# POST /api/v1/calculation-categories                   — [Admin] create a calc category
# DELETE /api/v1/calculation-categories/{id}             — [Admin] delete (non-builtin only)
# GET  /api/v1/calculation-categories/{id}/columns       — a calc category's field list + order
# PUT  /api/v1/calculation-categories/{id}/columns       — [Admin] set field list + order
# ============================================================

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List

from backend.auth import User, require_admin, get_db_for_auth
from backend.models import CategoryOrder, CalculationCategory, CalculationCategoryColumn

router = APIRouter(tags=["column-configurator"])


# ── Schemas ───────────────────────────────────────────────────
class CategoryOrderPayload(BaseModel):
    source: str
    categories: List[str]   # in desired order


class CalcCategoryCreatePayload(BaseModel):
    source: str
    name: str


class CalcCategoryColumnsPayload(BaseModel):
    db_columns: List[str]   # in desired final order


# ── Category order (All mode) ────────────────────────────────
@router.get("/category-order")
def get_category_order(source: str, db: Session = Depends(get_db_for_auth)):
    rows = (
        db.query(CategoryOrder)
        .filter(CategoryOrder.source == source)
        .order_by(CategoryOrder.sort_order.asc())
        .all()
    )
    return {"categories": [r.category for r in rows]}


@router.put("/category-order")
def save_category_order(
    payload: CategoryOrderPayload,
    db: Session = Depends(get_db_for_auth),
    _admin: User = Depends(require_admin),
):
    db.query(CategoryOrder).filter(CategoryOrder.source == payload.source).delete()
    for i, cat in enumerate(payload.categories):
        db.add(CategoryOrder(source=payload.source, category=cat, sort_order=i))
    db.commit()
    return {"status": "saved", "count": len(payload.categories)}


# ── Calculation categories ───────────────────────────────────
@router.get("/calculation-categories")
def list_calculation_categories(source: str, db: Session = Depends(get_db_for_auth)):
    rows = (
        db.query(CalculationCategory)
        .filter(CalculationCategory.source == source)
        .order_by(CalculationCategory.is_builtin.desc(), CalculationCategory.id.asc())
        .all()
    )
    return [
        {"id": r.id, "name": r.name, "is_builtin": r.is_builtin}
        for r in rows
    ]


@router.post("/calculation-categories")
def create_calculation_category(
    payload: CalcCategoryCreatePayload,
    db: Session = Depends(get_db_for_auth),
    _admin: User = Depends(require_admin),
):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Category name cannot be empty.")
    existing = db.query(CalculationCategory).filter(
        CalculationCategory.source == payload.source,
        CalculationCategory.name == name,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"A category named '{name}' already exists.")
    rec = CalculationCategory(source=payload.source, name=name, is_builtin=False)
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return {"id": rec.id, "name": rec.name, "is_builtin": rec.is_builtin}


@router.delete("/calculation-categories/{category_id}")
def delete_calculation_category(
    category_id: int,
    db: Session = Depends(get_db_for_auth),
    _admin: User = Depends(require_admin),
):
    rec = db.query(CalculationCategory).filter(CalculationCategory.id == category_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Category not found.")
    if rec.is_builtin:
        raise HTTPException(status_code=400, detail="Performance and Emission are built-in and cannot be deleted.")
    db.delete(rec)
    db.commit()
    return {"status": "deleted"}


# ── Calculation category columns (Section 3 in calc-category mode) ──
@router.get("/calculation-categories/{category_id}/columns")
def get_calc_category_columns(category_id: int, db: Session = Depends(get_db_for_auth)):
    rec = db.query(CalculationCategory).filter(CalculationCategory.id == category_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Category not found.")
    rows = (
        db.query(CalculationCategoryColumn)
        .filter(CalculationCategoryColumn.calculation_category_id == category_id)
        .order_by(CalculationCategoryColumn.sort_order.asc())
        .all()
    )
    return {"db_columns": [r.db_column for r in rows]}


@router.put("/calculation-categories/{category_id}/columns")
def save_calc_category_columns(
    category_id: int,
    payload: CalcCategoryColumnsPayload,
    db: Session = Depends(get_db_for_auth),
    _admin: User = Depends(require_admin),
):
    rec = db.query(CalculationCategory).filter(CalculationCategory.id == category_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Category not found.")
    db.query(CalculationCategoryColumn).filter(
        CalculationCategoryColumn.calculation_category_id == category_id
    ).delete()
    for i, db_col in enumerate(payload.db_columns):
        db.add(CalculationCategoryColumn(
            calculation_category_id=category_id, db_column=db_col, sort_order=i,
        ))
    db.commit()
    return {"status": "saved", "count": len(payload.db_columns)}
