from backend.database import engine, Base
from sqlalchemy import text
from backend.models import VesselColumnDefault

with engine.begin() as conn:
    print("Dropping vessel_column_defaults table...")
    conn.execute(text("DROP TABLE IF EXISTS vessel_column_defaults CASCADE"))
    print("Table dropped successfully!")

print("Re-creating vessel_column_defaults table...")
VesselColumnDefault.__table__.create(engine)
print("Done!")
