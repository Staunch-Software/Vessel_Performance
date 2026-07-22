# ============================================================
# DATABASE CONNECTION MODULE
# ============================================================
# Purpose: Manages database engine, sessions, and initialization
# Creates all tables and seeds initial data sources
# ============================================================

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from .config import config
from .models import Base, DataSource


# ============================================================
# DATABASE ENGINE & SESSION FACTORY
# ============================================================

# Create SQLAlchemy engine with PostgreSQL connection
engine = create_engine(config.DATABASE_URL)

# Session factory for creating database sessions
# Each session represents a "workspace" for database operations
SessionLocal = sessionmaker(bind=engine)


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

def init_db():
    """
    Initialize database schema and seed reference data
    
    Operations:
    1. Creates all tables defined in models.py
    2. Seeds the data_sources table with standard providers
    
    Data Sources:
    - wni: Weathernews Inc. (primary source)
    - read_at_sea: Read at Sea platform
    - mari_apps: Mari Apps Native reports
    - old_data: Legacy/historical data imports
    """
    
    # Create all tables from SQLAlchemy models
    Base.metadata.create_all(bind=engine)
    
    # Open database session
    db = SessionLocal()
    
    try:
        # Define standard data sources
        sources = [
            DataSource(source_id="wni", source_name="Weathernews"),
            DataSource(source_id="read_at_sea", source_name="Read at Sea"),
            DataSource(source_id="mari_apps", source_name="Mari Apps Native"),
            DataSource(source_id="old_data", source_name="Legacy Data")
        ]
        
        # Insert only if not already present (idempotent operation)
        for s in sources:
            if not db.query(DataSource).get(s.source_id):
                db.add(s)
        
        db.commit()
        print("Database Initialized with Providers.")

        # ── Seed default admin user if no users exist ──────────────────
        # Imported here to avoid circular imports at module load time.
        try:
            from .auth import User, hash_password
            if db.query(User).count() == 0:
                admin = User(
                    username="admin",
                    email="admin@vesselpref.com",
                    hashed_password=hash_password("Admin@123"),
                    role="admin",
                    is_active=True,
                )
                db.add(admin)
                db.commit()
                print("✅ Default admin user seeded (admin@vesselpref.com).")
        except Exception as seed_err:
            print(f"⚠️  Admin seed skipped: {seed_err}")
        
    finally:
        # Always close the session
        db.close()


# ============================================================
# SCRAPE VESSEL LIST (per-source, DB-driven)
# ============================================================

# Vessels covered by the WNI (Weathernews) portal. Used only to SEED the
# wni_enabled flag the first time the column is created — after that the DB
# column is the source of truth and can be edited freely (the backfill below
# only touches NULLs). MariApps covers all vessels, so mari_enabled defaults TRUE.
_WNI_DEFAULT_VESSELS = {
    "AM KIRTI", "AM TARANG", "AM UMANG",
    "GCL GANGA", "GCL NARMADA", "GCL SABARMATI",
    "GCL SARASWATI", "GCL TAPI", "GCL YAMUNA",
}


def _ensure_scrape_flags():
    """Idempotently add + seed the per-source scrape flags on `vessels`.

    - Adds nullable BOOLEAN columns wni_enabled / mari_enabled if missing.
    - Seeds only rows where the flag is still NULL (never overwrites edits):
        * mari_enabled -> TRUE for all vessels (MariApps covers everything)
        * wni_enabled  -> TRUE only for the known WNI portal vessels, else FALSE
    Safe to call on every pipeline run.
    """
    with engine.begin() as conn:
        conn.execute(text(
            'ALTER TABLE vessels ADD COLUMN IF NOT EXISTS wni_enabled BOOLEAN'))
        conn.execute(text(
            'ALTER TABLE vessels ADD COLUMN IF NOT EXISTS mari_enabled BOOLEAN'))
        conn.execute(text(
            'UPDATE vessels SET mari_enabled = TRUE WHERE mari_enabled IS NULL'))
        # Seed wni_enabled by membership in the known WNI vessel set.
        conn.execute(
            text('UPDATE vessels SET wni_enabled = (vessel_name = ANY(:names)) '
                 'WHERE wni_enabled IS NULL'),
            {"names": list(_WNI_DEFAULT_VESSELS)},
        )


def get_scrape_vessels(source: str):
    """Return the list of vessel names to scrape for a given source.

    source: "wni" or "mari_apps". Reads the DB flag column so the vessel list
    is fully data-driven (no hardcoded names in the pipelines).
    """
    _ensure_scrape_flags()
    col = {"wni": "wni_enabled", "mari_apps": "mari_enabled"}.get(source)
    if col is None:
        raise ValueError(f"Unknown scrape source: {source!r}")
    with engine.connect() as conn:
        rows = conn.execute(text(
            f'SELECT vessel_name FROM vessels WHERE {col} = TRUE '
            'ORDER BY vessel_name'
        )).fetchall()
    return [r[0] for r in rows]


# ============================================================
# DIRECT EXECUTION
# ============================================================

if __name__ == "__main__":
    init_db()