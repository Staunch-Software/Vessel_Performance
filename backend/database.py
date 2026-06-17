# ============================================================
# DATABASE CONNECTION MODULE
# ============================================================
# Purpose: Manages database engine, sessions, and initialization
# Creates all tables and seeds initial data sources
# ============================================================

from sqlalchemy import create_engine
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
        print("✅ Database Initialized with Providers.")
        
    finally:
        # Always close the session
        db.close()


# ============================================================
# DIRECT EXECUTION
# ============================================================

if __name__ == "__main__":
    init_db()