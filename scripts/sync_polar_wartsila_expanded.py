"""
Sync Polar Wartsila FOS records from noon_report_data + analysis_data into expanded_wni_data.
Run manually if expanded_wni_data was truncated or missing Polar Wartsila rows:
    python -m scripts.sync_polar_wartsila_expanded
"""
import sys
from sqlalchemy import text
from backend.database import SessionLocal

def sync():
    db = SessionLocal()
    try:
        print("Checking Polar records in noon_report_data...")
        total_noon = db.execute(text(
            "SELECT count(DISTINCT n.raw_report_id) FROM noon_report_data n "
            "JOIN analysis_data a ON a.raw_report_id = n.raw_report_id "
            "WHERE n.source_id = 'Wartsila FOS' AND n.vessel_imo IN ('9961609', '9521813')"
        )).scalar()
        print(f"Found {total_noon} Polar Wartsila reports to sync.")

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
        res = db.execute(sync_sql)
        db.commit()
        print(f"Successfully synced {res.rowcount} records into expanded_wni_data.")
    except Exception as e:
        db.rollback()
        print(f"Error during sync: {e}")
        sys.exit(1)
    finally:
        db.close()

if __name__ == '__main__':
    sync()
