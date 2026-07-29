import os
import sys

# Add the root directory to the python path so we can import backend modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from backend.database import engine, SessionLocal

# Owner mapping from our hardcoded logic
_OWNER_GROUP_MAP = {
    "GCL GANGA":     "Umang Shipping Private LTD",
    "GCL NARMADA":   "Umang Shipping Private LTD",
    "GCL SABARMATI": "Umang Shipping Private LTD",
    "GCL TAPI":      "Umang Shipping Private LTD",
    "GCL YAMUNA":    "Umang Shipping Private LTD",
    "AM TARANG":     "Global Chartering Limited",
    "AM KIRTI":      "Global Chartering Limited",
    "AM UMANG":      "Global Chartering Limited",
    "GCL SARASWATI": "Global Chartering Limited",
    "GCL FOS":       "Global Chartering Limited",
}
_AMNS_OWNER = "AMNS Shipping & Logistics Private Limited"

def get_owner_group(vessel_name):
    key = (vessel_name or "").strip().upper()
    if key in _OWNER_GROUP_MAP:
        return _OWNER_GROUP_MAP[key]
    if key.startswith("AMNS ") or key.startswith("AMNSI "):
        return _AMNS_OWNER
    return "Other"

def migrate():
    with engine.connect() as conn:
        # 1. Add the column (ignoring error if it already exists)
        try:
            conn.execute(text("ALTER TABLE vessels ADD COLUMN owner_group VARCHAR(255);"))
            conn.commit()
            print("Added owner_group column.")
        except Exception as e:
            if "already exists" in str(e).lower() or "duplicate column name" in str(e).lower():
                print("Column owner_group already exists.")
            else:
                print(f"Error adding column (might already exist): {e}")

        # 2. Fetch all vessels and update them
        result = conn.execute(text("SELECT imo_number, vessel_name FROM vessels;"))
        vessels = result.fetchall()
        
        for imo_number, vessel_name in vessels:
            owner = get_owner_group(vessel_name)
            conn.execute(
                text("UPDATE vessels SET owner_group = :owner WHERE imo_number = :imo"),
                {"owner": owner, "imo": imo_number}
            )
            print(f"Updated {vessel_name} (IMO: {imo_number}) -> {owner}")
            
        conn.commit()
        print("Migration complete!")

if __name__ == "__main__":
    migrate()
