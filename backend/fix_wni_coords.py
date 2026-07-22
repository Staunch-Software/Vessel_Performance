import sys
import os

# Add root to python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.database import SessionLocal
from backend.models import RawNoonReport, NoonReportData
from backend.pipeline.mapping import parse_coord

db = SessionLocal()
reports = db.query(NoonReportData).all()
count = 0

for nd in reports:
    raw = db.query(RawNoonReport).get(nd.raw_report_id)
    if raw:
        lat_d, lat_m, lat_dir = parse_coord(str(raw.raw_json.get('Position_Lat', '')))
        lon_d, lon_m, lon_dir = parse_coord(str(raw.raw_json.get('Position_Long', '')))
        
        nd.lat_degree = lat_d
        nd.lat_minutes = lat_m
        nd.lat_direction = lat_dir
        nd.lon_degree = lon_d
        nd.lon_minutes = lon_m
        nd.lon_direction = lon_dir
        count += 1

db.commit()
print(f'Successfully updated {count} WNI records with coordinates!')
db.close()
