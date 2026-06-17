import logging
import os
from fastapi import FastAPI, Depends, HTTPException, APIRouter
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from api.routes.vessel_routes import router as vessel_router
from api.routes.expanded_routes import router as expanded_router
from api.routes.vessel_design_routes import router as vessel_design_router
from api.routes.iso_routes import router as iso_router
from fastapi.middleware.cors import CORSMiddleware 
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from datetime import datetime

# Import necessary components from your existing backend structure
from backend.database import engine, init_db
from backend.database_utils import init_mariapps_database
from backend.pipeline.processor import save_to_db # Example import
from backend.models import AnalysisData
from api.routes.vessel_routes import get_db 

# Setup logging for the FastAPI application
log = logging.getLogger("uvicorn")
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Lifespan Management (Startup/Shutdown Events) ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP EVENT ---
    log.info("🚀 FastAPI Application Startup: Initializing Database Schema and Data Sources")
    
    # 1. Initialize WNI/General DB Schema (Creates tables, seeds providers)
    try:
        init_db()
        log.info("✅ WNI/Core Database initialized.")
    except Exception as e:
        log.error(f"Failed to initialize core database: {e}")
        # In a real app, you might raise an exception here to stop startup

    # 2. Initialize MariApps specific schema changes
    try:
        init_mariapps_database()
        log.info("✅ MariApps specific database schema adjustments complete.")
    except Exception as e:
        log.error(f"Failed to initialize MariApps database utilities: {e}")

    # 3. Backfill AE_FOC_MT for existing rows where it is NULL.
    #    WNI:       map_analysis_row() never set AE_FOC_MT — pull from noon_report_data.ae_total_cons
    #    MariApps:  fuel search term "Aux Engine" didn't match "Auxilary Engine" (MariApps typo)
    #               — pull directly from raw_mariapps_logs.raw_json Excel_Data
    # Both queries are idempotent (only touch rows where AE_FOC_MT IS NULL).

    # 3a. MariApps backfill
    try:
        from sqlalchemy import text as _text
        from backend.database import engine as _eng
        with _eng.connect() as _conn:
            result = _conn.execute(_text("""
                UPDATE analysis_data a
                SET    "AE_FOC_MT" = (
                    TRIM(r.raw_json->'Excel_Data'->>'Auxilary Engine Consumption (MT) - AE Total Cons')
                )::float
                FROM   raw_mariapps_logs r
                WHERE  r.id            = a.raw_mariapps_id
                  AND  a."AE_FOC_MT"  IS NULL
                  AND  a.source_id    = 'mari_apps'
                  AND  TRIM(COALESCE(
                         r.raw_json->'Excel_Data'->>'Auxilary Engine Consumption (MT) - AE Total Cons',
                         ''
                       )) ~ '^[0-9]+\.?[0-9]*$'
            """))
            _conn.commit()
            log.info(f"✅ AE_FOC_MT MariApps backfill: {result.rowcount} rows updated.")
    except Exception as e:
        log.error(f"AE_FOC_MT MariApps backfill failed: {e}")

    # 3b. WNI backfill — pull ae_total_cons from noon_report_data (already mapped by map_row())
    # Backfill AE_FOC_MT for existing WNI analysis_data rows where it is NULL.
    #    Root cause: map_analysis_row() in pipeline/mapping.py never set AE_FOC_MT.
    #    Fix: pull ae_total_cons from noon_report_data (already computed by map_row).
    #    This is idempotent — only touches rows where AE_FOC_MT IS NULL.
    try:
        from sqlalchemy import text as _text
        from backend.database import engine as _eng
        with _eng.connect() as _conn:
            result = _conn.execute(_text("""
                UPDATE analysis_data a
                SET    "AE_FOC_MT" = n.ae_total_cons::float
                FROM   noon_report_data n
                WHERE  n.raw_report_id = a.raw_report_id
                  AND  a."AE_FOC_MT"  IS NULL
                  AND  a.source_id    = 'wni'
                  AND  n.ae_total_cons IS NOT NULL
            """))
            _conn.commit()
            log.info(f"✅ AE_FOC_MT backfill: {result.rowcount} WNI rows updated.")
    except Exception as e:
        log.error(f"AE_FOC_MT backfill failed: {e}")

    # 4. Set up expanded flat tables (creates + backfills on first run)
    try:
        from backend.pipeline.expander import setup_expanded_tables
        from backend.database import engine as db_engine
        setup_expanded_tables(db_engine)
        log.info("✅ Expanded tables ready.")
    except Exception as e:
        log.error(f"Failed to setup expanded tables: {e}")

    # 5. ISO 19030 backfill — process all existing analysis_data records for
    #    any vessel that already has an ISO config saved.
    #    Idempotent: uses ON CONFLICT UPDATE so re-running is safe.
    #    Skipped if no vessel has ISO config yet (user hasn't set it up).
    try:
        from sqlalchemy import text as _text
        from backend.database import engine as _eng
        from backend.iso19030.runner import run_for_vessel
        from backend.database import SessionLocal as _SL

        with _eng.connect() as _conn:
            configured_vessels = _conn.execute(_text(
                "SELECT vessel_imo FROM vessel_iso_config"
            )).fetchall()

        if configured_vessels:
            db = _SL()
            try:
                for (imo,) in configured_vessels:
                    log.info(f"ISO 19030 backfill: processing {imo} …")
                    summary = run_for_vessel(imo, db)
                    log.info(
                        f"✅ ISO 19030 backfill {imo}: "
                        f"{summary['pass']} PASS, {summary['excl']} EXCL, "
                        f"{summary['errors']} errors"
                    )
            finally:
                db.close()
        else:
            log.info("ISO 19030 backfill: no configured vessels yet — skipping.")
    except Exception as e:
        log.error(f"ISO 19030 backfill failed: {e}")

    # NOTE: You might want to run your historical importers (like import_history.py) 
    # here if you want them to run once upon application start, but typically 
    # importers are run as separate cron jobs or CLI commands.
    
    yield
    
    # --- SHUTDOWN EVENT ---
    log.info("🛑 FastAPI Application Shutdown")
    # Clean up resources if necessary (e.g., closing Playwright browser instances if they were global)


# --- FastAPI Application Setup ---
app = FastAPI(
    title="Maritime Data Backend",
    description="API for managing WNI, MariApps, and Eyegauge data ingestion.",
    version="0.1.0",
    lifespan=lifespan
)
# --- CORS CONFIGURATION ---
# --- LOCAL (original hardcoded origins — uncomment to use) ---
# origins = [
#     "http://localhost:3000",
#     "http://127.0.0.1:3000",
#     "http://localhost:5173",
#     "http://localhost:5174",
# ]
# --- VM / CROSS-PLATFORM (env var CORS_ORIGINS, comma-separated; default = local dev origins) ---
_cors_env = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173,http://localhost:5174")
origins = [o.strip() for o in _cors_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # Allow requests from these origins
    allow_credentials=False, # Allow cookies/credentials (important if you use session auth)
    allow_methods=["*"],    # Allow all HTTP methods (GET, POST, etc.)
    allow_headers=["*"],    # Allow all headers
)
# --- Register Routes ---
app.include_router(vessel_router,        prefix="/api/v1")
app.include_router(expanded_router,      prefix="/api/v1")
app.include_router(vessel_design_router, prefix="/api/v1")
app.include_router(iso_router,           prefix="/api/v1")


# --- DEFINE /analysis/query ENDPOINT DIRECTLY HERE ---
# This bypasses potential issues with router registration for this specific endpoint.
@app.post("/analysis/query", response_model=List[Dict[str, Any]])
async def query_analysis_data_direct(filters: dict, db: Session = Depends(get_db)):
    """
    Fetches analysis data based on provided filters (voyageNo, fromDate, toDate, loadingConditions).
    """
    try:
        # Extract filters from the request body
        voyage_no = filters.get("voyageNo")
        from_date_str = filters.get("fromDate")
        to_date_str = filters.get("toDate")
        loading_conditions = filters.get("loadingConditions", [])

        # --- Build the base query ---
        query = db.query(AnalysisData)

        # --- Apply filters ---
        if voyage_no:
            query = query.filter(AnalysisData.Voyage_No == voyage_no)
        
        if from_date_str:
            from_date = datetime.strptime(from_date_str, '%Y-%m-%d')
            query = query.filter(AnalysisData.Date >= from_date)
        
        if to_date_str:
            to_date = datetime.strptime(to_date_str, '%Y-%m-%d')
            query = query.filter(AnalysisData.Date <= to_date)
        
        if loading_conditions:
            query = query.filter(AnalysisData.Loading_Cond.in_(loading_conditions))

        # --- Execute the query ---
        results = query.all()

        # --- Format results ---
        analysis_results = []
        for row in results:
            row_dict = {
                "id": row.id, "Voyage_No": row.Voyage_No, "Loading_Cond": row.Loading_Cond,
                "From_Port": row.From_Port, "To_Port": row.To_Port,
                "Date": row.Date.isoformat() if row.Date else None, "Record_ID": row.Record_ID,
                "ME_FOC_MT": row.ME_FOC_MT, "Duration_h": row.Duration_h,
                "vlsfo": row.ME_FOC_MT, "lsmgo": row.AE_FOC_MT, "bio": row.AE_FOC_MT,
                "timeSaved": row.Duration_h
            }
            analysis_results.append(row_dict)

        return analysis_results

    except Exception as e:
        logging.error(f"Error in /analysis/query endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to load analysis: {e}")
# --- END OF DIRECTLY DEFINED ENDPOINT ---


# --- Root Endpoint ---
@app.get("/")
async def root():
    return {"message": "Backend Service Running", "status": "OK"}

# --- Example Endpoint to trigger a pipeline function (Optional) ---
# This shows how you would call your existing logic from a route
# @app.post("/pipeline/import_history")
# async def trigger_history_import():
#     from backend.pipeline.import_history import import_historical_data
#     # Note: Running blocking I/O like Playwright in an async endpoint requires
#     # running it in a thread pool executor (using run_in_executor), 
#     # but for simple testing, we'll just log it.
#     log.warning("Triggering import_historical_data. This is a blocking call and should be handled asynchronously in production.")
#     # import_historical_data() # Don't run blocking code directly in production API routes!
#     return {"status": "Import triggered (check logs for execution status)"}

# --- Example Endpoint to trigger a reporting function (Optional) ---
# @app.post("/reporting/run_weekly")
# async def trigger_weekly_report():
#     from backend.reporting.run_weekly_report import main as run_weekly_main
#     # This is also blocking I/O (DB queries + Email sending)
#     log.warning("Triggering weekly report generation. This is a blocking call.")
#     # run_weekly_main() # Again, handle blocking tasks via background tasks or Celery in production
#     return {"status": "Weekly report generation initiated (check logs)"}