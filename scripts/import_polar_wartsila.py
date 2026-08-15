import sys
import os
import pandas as pd
from datetime import datetime
import re

def parse_coord(coord_str):
    if not isinstance(coord_str, str):
        return None, None, None
    match = re.search(r'(\d+)\D+(\d+\.?\d*)\D+([NSEW])', coord_str, re.IGNORECASE)
    if match:
        return str(match.group(1)), str(match.group(2)), match.group(3).upper()
    return None, None, None


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import text
from backend.database import SessionLocal
from backend.models import Vessel, DataSource, AnalysisData, NoonReportData, RawNoonReport

def parse_hours(val):
    if pd.isna(val):
        return None
    try:
        val_str = str(val).strip()
        if ':' in val_str:
            parts = val_str.split(':')
            if len(parts) >= 2:
                h = float(parts[0])
                m = float(parts[1])
                return h + (m / 60.0)
        return float(val_str)
    except (ValueError, TypeError):
        return None

def main():
    excel_file = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'AMNS POLAR. Emissions report for Jan 1, 2026 - Aug 15, 2026.xlsx'))
    if not os.path.exists(excel_file):
        print(f"File not found: {excel_file}")
        return

    print("Reading Excel file...")
    try:
        df = pd.read_excel(excel_file, sheet_name='Log Abstract')
    except Exception as e:
        print(f"Error reading excel: {e}")
        return

    db = SessionLocal()
    
    try:
        vessel = db.query(Vessel).filter(Vessel.vessel_name.ilike('%POLAR%')).first()
        if not vessel:
            print("Vessel AMNS POLAR not found in database.")
            return
        
        imo = vessel.imo_number
        print(f"Found vessel AMNS POLAR with IMO: {imo}")

        source_id = 'Wartsila FOS'
        source = db.query(DataSource).filter_by(source_id=source_id).first()
        if not source:
            source = DataSource(source_id=source_id, source_name='Wartsila FOS Data')
            db.add(source)
            db.commit()
            print(f"Created data source: {source_id}")

        print("Clearing old records for Wartsila FOS...")
        db.execute(text(f"DELETE FROM expanded_wni_data WHERE source_id = '{source_id}'"))
        db.query(AnalysisData).filter(AnalysisData.source_id == source_id).delete()
        db.query(NoonReportData).filter(NoonReportData.source_id == source_id).delete()
        db.query(RawNoonReport).filter(RawNoonReport.source_id == source_id).delete()
        db.commit()

        inserted_count = 0
        
        for index, row in df.iterrows():
            if pd.isna(row.get('NOON TIME')):
                continue

            dt = row['NOON TIME']
            if isinstance(dt, str):
                try:
                    dt = pd.to_datetime(dt)
                except:
                    continue
            
            if not isinstance(dt, pd.Timestamp) and not isinstance(dt, datetime):
                continue

            date_val = dt.date()
            time_val = dt.time()

            dist = row.get('DISTANCE [NM]')
            dist = float(dist) if pd.notna(dist) else None

            dur_str = row.get('TIME SINCE LAST REPORT [H]')
            dur = parse_hours(dur_str)

            sog = None
            if dist is not None and dur and dur > 0:
                sog = dist / dur

            lfo = row.get('LFO [MT]')
            mgo = row.get('MGO [MT]')
            lfo = float(lfo) if pd.notna(lfo) else None
            mgo = float(mgo) if pd.notna(mgo) else None

            from_port = str(row.get('FROM')) if pd.notna(row.get('FROM')) else None
            to_port = str(row.get('TO')) if pd.notna(row.get('TO')) else None
            voyage_no = str(row.get('VOYAGE NUMBER')) if pd.notna(row.get('VOYAGE NUMBER')) else None
            event_type = None
            if pd.notna(row.get('Event ')):
                event_type = str(row.get('Event ')).strip()
            
            if not event_type or event_type.lower() == 'nan':
                un_5 = str(row.get('Unnamed: 5', '')).lower()
                if 'in port' in un_5:
                    event_type = 'Noon at port'
                elif 'arrival' in un_5:
                    event_type = 'EOSP'
                elif 'departure' in un_5:
                    event_type = 'COSP'
                elif 'position' in un_5:
                    event_type = 'Noon At Sea'
                else:
                    event_type = 'Noon at port'

            # 1. Create Raw record
            raw = RawNoonReport(
                vessel_imo=imo,
                source_id=source_id,
                raw_json="{}",
                file_name="AMNS_POLAR_Excel"
            )
            db.add(raw)
            db.commit()

            # 2. Create NoonReportData
            noon = NoonReportData(
                raw_report_id=raw.id,
                vessel_imo=imo,
                source_id=source_id,
                log_type=event_type,
                log_date_utc=dt,
                log_date=dt,
                distance_og=dist,
                log_duration=dur,
                to_port=to_port,
                me_lfo=str(lfo) if lfo is not None else None,
                ae_mdo=str(mgo) if mgo is not None else None
            )
            db.add(noon)
            
            # 3. Create AnalysisData
            analysis = AnalysisData(
                raw_report_id=raw.id,
                vessel_imo=imo,
                source_id=source_id,
                Date=date_val,
                Time_UTC=time_val,
                Voyage_No=voyage_no,
                From_Port=from_port,
                To_Port=to_port,
                Distance_nm=dist,
                Duration_h=dur,
                SOG_kn=sog,
                ME_FOC_MT=lfo,
                AE_FOC_MT=mgo,
                Loading_Cond=("Laden" if str(row.get('LEG PURPOSE')).startswith('Cargo') else "Ballast" if str(row.get('LEG PURPOSE')) == 'Ballast' else None)
            )
            db.add(analysis)
            
            lat_deg, lat_min, lat_dir = parse_coord(row.get('LAT'))
            lon_deg, lon_min, lon_dir = parse_coord(row.get('LON'))

            # 4. Insert into expanded_wni_data
            sql = text("""
                INSERT INTO expanded_wni_data (
                    raw_report_id, vessel_imo, source_id, date, event_type, voyage_no, loading_condition,
                    "VoyageMeta_log_durationh_operational_LF",
                    "wnix_distance_nm_reported_distance_nm",
                    "wnix_m_e_fuel_consumption_vlsfo_hfo_mt",
                    "wnix_a_e_fuel_consumption_vlsfo_lfo_mt",
                    "wnix_total_fuel_consumption_lfo_mt",
                    "VoyageMeta_to_port_operational_LF",
                    "VoyageMeta_latitude_lat_degree_operational_LF",
                    "VoyageMeta_latitude_lat_minutes_operational_LF",
                    "VoyageMeta_latitude_lat_direction_operational_LF",
                    "VoyageMeta_longitude_lon_degree_operational_LF",
                    "VoyageMeta_longitude_lon_minutes_operational_LF",
                    "VoyageMeta_longitude_lon_direction_operational_LF"
                ) VALUES (
                    :raw_id, :imo, :src, :date_val, :ev_type, :voy, :lc,
                    :dur, :dist, :lfo, :mgo, :tot_lfo, :to_port,
                    :lat_deg, :lat_min, :lat_dir,
                    :lon_deg, :lon_min, :lon_dir
                )
            """)
            db.execute(sql, {
                "raw_id": raw.id,
                "imo": imo,
                "src": source_id,
                "date_val": date_val,
                "ev_type": event_type,
                "voy": voyage_no,
                "lc": ("Laden" if str(row.get('LEG PURPOSE')).startswith('Cargo') else "Ballast" if str(row.get('LEG PURPOSE')) == 'Ballast' else None),
                "dur": str(dur) if dur is not None else None,
                "dist": str(dist) if dist is not None else None,
                "lfo": str(lfo) if lfo is not None else None,
                "mgo": str(mgo) if mgo is not None else None,
                "tot_lfo": str((lfo or 0) + (mgo or 0)),
                "to_port": to_port,
                "lat_deg": lat_deg,
                "lat_min": lat_min,
                "lat_dir": lat_dir,
                "lon_deg": lon_deg,
                "lon_min": lon_min,
                "lon_dir": lon_dir
            })

            inserted_count += 1

        db.commit()
        print(f"Successfully inserted {inserted_count} valid records (Raw+Noon+Analysis).")

    except Exception as e:
        db.rollback()
        print(f"Database error: {e}")
    finally:
        db.close()

if __name__ == '__main__':
    main()
