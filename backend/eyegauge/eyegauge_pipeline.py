"""
eyegauge_pipeline.py
====================
Contains TWO pipeline classes:

  EyegaugeBackwardsPipeline  — original Method 1 (raw requests, day-by-day
                                backwards loop, Jan–Feb 2025 historical fill)

  EyegaugePipeline           — new Method 2 (tb-rest-client SDK, Sep 2025 →
                                today, stores into raw_eyegauge_logs,
                                eyegauge_elementary AND analysis_data)

Run from your launcher file:
    from backend.eyegauge.eyegauge_pipeline import EyegaugeBackwardsPipeline
    from backend.eyegauge.eyegauge_pipeline import EyegaugePipeline
"""

import pandas as pd
import numpy as np
import json
import logging
import sys
from pathlib import Path
from sqlalchemy import create_engine, text
from datetime import datetime, timedelta, timezone

# ── path setup ───────────────────────────────────────────────────────────────
current_dir = Path(__file__).resolve().parent
parent_dir  = current_dir.parent
sys.path.append(str(current_dir))   # backend/eyegauge  — for auth_client, telemetry_client, eyegauge_mapping
sys.path.append(str(parent_dir))    # backend/           — for config

from backend.config import config
from backend.eyegauge.auth_client import EyegaugeAuthClient
from backend.eyegauge.telemetry_client import EyegaugeTelemetryClient
from backend.eyegauge.eyegauge_mapping import map_eyegauge_analysis_row, ANALYSIS_DATA_COLUMNS
from backend.eyegauge.eyegauge_exporter import EyegaugeExcelExporter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# =============================================================================
# Shared helpers (used by both pipeline classes)
# =============================================================================

def clean_name(name):
    return f"sensor_{str(name).replace('-', '_').replace(' ', '_').replace('.', '_').lower()}"


def to_json_str(val):
    if isinstance(val, dict):
        return json.dumps(val)
    return val


def clean_dict(d: dict) -> dict:
    """Replace NaN / inf with None so Postgres accepts the values."""
    cleaned = {}
    for k, v in d.items():
        try:
            if v is not None and pd.isna(v):
                cleaned[k] = None
                continue
        except (TypeError, ValueError):
            pass
        cleaned[k] = v
    return cleaned


# =============================================================================
# CLASS 1 — Original backwards historical pipeline (Method 1, UNCHANGED)
# =============================================================================

class EyegaugeBackwardsPipeline:
    def __init__(self):
        self.engine = create_engine(config.DATABASE_URL)
        self.vessel_name = "am-tarang"
        self.vessel_imo = "9832913"
        self.source_id = "Eyegauge_API"

    def run(self):
        try:
            # --- STEP 1: LOGIN ---
            auth = EyegaugeAuthClient(config.EYEGAUGE_BASE_URL, config.EYEGAUGE_USERNAME, config.EYEGAUGE_PASSWORD)
            token = auth.get_token()
            client = EyegaugeTelemetryClient(config.EYEGAUGE_BASE_URL, token)
            entities = client.get_all_entities()

            # --- STEP 2: DEFINE EXACT BACKWARDS RANGE ---
            # Start: Feb 27, 2025 | End: Jan 1, 2025
            start_date = datetime(2025, 2, 27, tzinfo=timezone.utc)
            end_date = datetime(2025, 1, 1, tzinfo=timezone.utc)
            
            historical_points = []
            logger.info(f"STARTING BACKWARDS FETCH: From {start_date.date()} back to {end_date.date()}")

            # Loop backwards day by day
            current_day = start_date
            while current_day >= end_date:
                day_start_ts = int(current_day.replace(hour=0, minute=0, second=0).timestamp() * 1000)
                day_end_ts = int(current_day.replace(hour=23, minute=59, second=59).timestamp() * 1000)
                
                logger.info(f"Fetching Day (Moving Backwards): {current_day.strftime('%Y-%m-%d')}")
                
                for ent in entities:
                    keys = client.get_available_keys(ent['type'], ent['guid'])
                    if not keys: continue
                    
                    temp_start = day_start_ts
                    while temp_start < day_end_ts:
                        data = client.fetch_telemetry(ent['type'], ent['guid'], keys, temp_start, day_end_ts)
                        if not data or all(len(v) == 0 for v in data.values()): break
                        
                        max_ts = temp_start
                        for key, values in data.items():
                            for v in values:
                                ts = v[0] if isinstance(v, list) else v.get('ts')
                                val = v[1] if isinstance(v, list) else v.get('value')
                                historical_points.append({'ts': ts, 'key': key, 'val': val})
                                if ts > max_ts: max_ts = ts
                        
                        if max_ts > temp_start: temp_start = max_ts + 1
                        else: break
                
                # Move to the previous day
                current_day -= timedelta(days=1)

            # --- STEP 3: LOAD EXISTING DATA FROM PGADMIN ---
            logger.info("Reading existing data from pgAdmin...")
            with self.engine.connect() as conn:
                try:
                    df_existing = pd.read_sql("SELECT vessel_name, vessel_imo, source_id, timestamp, raw_data FROM raw_eyegauge_logs", conn)
                except:
                    df_existing = pd.DataFrame()

            # --- STEP 4: PROCESS NEW DATA ---
            if historical_points:
                df_hist = pd.DataFrame(historical_points)
                df_hist['timestamp'] = pd.to_datetime((df_hist['ts'] // 1000) * 1000, unit='ms')
                df_pivot = df_hist.pivot_table(index='timestamp', columns='key', values='val', aggfunc='first').reset_index()
                
                sensor_cols = [c for c in df_pivot.columns if c != 'timestamp']
                new_records = []
                for _, row in df_pivot.iterrows():
                    json_blob = {col: row[col] for col in sensor_cols if pd.notnull(row[col])}
                    new_records.append({
                        "vessel_name": self.vessel_name, "vessel_imo": self.vessel_imo,
                        "source_id": self.source_id, "timestamp": row['timestamp'],
                        "raw_data": json_blob
                    })
                df_new = pd.DataFrame(new_records)
            else:
                df_new = pd.DataFrame()

            # --- STEP 5: MERGE AND SORT CHRONOLOGICALLY ---
            df_combined = pd.concat([df_new, df_existing], ignore_index=True)
            df_combined = df_combined.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
            df_combined['raw_data'] = df_combined['raw_data'].apply(to_json_str)

            # --- STEP 6: RE-INSERT EVERYTHING ---
            logger.info(f"Re-inserting {len(df_combined)} rows. ID 1 will be {df_combined['timestamp'].min()}")
            with self.engine.begin() as conn:
                conn.execute(text("TRUNCATE TABLE raw_eyegauge_logs RESTART IDENTITY CASCADE"))
                df_combined.to_sql("raw_eyegauge_logs", conn, if_exists='append', index=False)

            # --- STEP 7: SYNC ELEMENTARY TABLE ---
            with self.engine.connect() as conn:
                df_final_raw = pd.read_sql("SELECT * FROM raw_eyegauge_logs ORDER BY id ASC", conn)

            json_list = df_final_raw['raw_data'].apply(lambda x: json.loads(x) if isinstance(x, str) else x).tolist()
            df_sensors = pd.DataFrame(json_list)
            df_sensors.columns = [clean_name(c) for c in df_sensors.columns]
            
            df_elem = pd.concat([df_final_raw[['id', 'vessel_name', 'vessel_imo', 'source_id', 'timestamp']], df_sensors], axis=1)
            
            for col in df_elem.columns:
                if col.startswith('sensor_'):
                    df_elem[col] = pd.to_numeric(df_elem[col], errors='coerce')

            with self.engine.begin() as conn:
                df_elem.to_sql("eyegauge_elementary", conn, if_exists='replace', index=False)
                conn.execute(text("ALTER TABLE eyegauge_elementary ADD PRIMARY KEY (id)"))

            logger.info(f"SUCCESS! Data range: {df_elem['timestamp'].min()} to {df_elem['timestamp'].max()}")

        except Exception as e:
            logger.error(f"Failed: {e}")
            import traceback
            traceback.print_exc()


# =============================================================================
# CLASS 2 — New SDK pipeline (Method 2, Sep 2025 → today, 3 tables)
# =============================================================================

class EyegaugePipeline:
    """
    Uses the official tb-rest-client SDK to fetch telemetry from Sea Vision.
    Stores data into THREE tables (same schema as WNI):
      - raw_eyegauge_logs
      - eyegauge_elementary
      - analysis_data  (57 columns, identical to WNI analysis_data)
    """

    VESSEL_NAME = "am-tarang"
    VESSEL_IMO  = "9832913"
    SOURCE_ID   = "Eyegauge_API"

    FETCH_START = datetime(2026, 3, 22, 0, 0, 0, tzinfo=timezone.utc)

    def __init__(self):
        self.engine = create_engine(config.DATABASE_URL)

    def run(self):
        fetch_end = datetime.now(tz=timezone.utc)
        logger.info(
            f"Starting Eyegauge Pipeline  [{self.FETCH_START.date()} -> {fetch_end.date()}]"
        )

        client = EyegaugeTelemetryClient(
            base_url=config.EYEGAUGE_BASE_URL,
            username=config.EYEGAUGE_USERNAME,
            password=config.EYEGAUGE_PASSWORD,
        )

        try:
            # STEP 1 — Login via SDK
            client.login()

            # STEP 2 — Fetch all telemetry (ASSET + DEVICEs) in one call
            logger.info("Connecting to Sea Vision ...")

            # Fetch asset_id first so we can read ASSET attributes (voyage number)
            asset_id, asset_name = client._get_asset_by_imo(self.VESSEL_IMO)
            if asset_id is None:
                raise ValueError(f"No vessel found for IMO {self.VESSEL_IMO}")
            logger.info(f"Vessel found: {asset_name}")

            # Fetch voyage number from ASSET attributes and fix any nan rows in DB
            voyage_no = None

            df_wide = client.get_all_data(
                imo=self.VESSEL_IMO,
                start_dt=self.FETCH_START,
                end_dt=fetch_end,
                max_data_points=100_000,
                wanted_keys=None,
            )

            if df_wide.empty:
                logger.warning("No telemetry data returned. Exiting.")
                return

            logger.info(
                f"Data fetch complete — {len(df_wide)} hourly rows, {len(df_wide.columns)} sensor columns."
            )

            # STEP 3 — raw_eyegauge_logs
            logger.info("Saving raw data to database ...")
            df_new      = self._build_raw_records(df_wide)
            df_combined = self._merge_with_existing(df_new)
            self._write_raw_table(df_combined)

            # STEP 4 — eyegauge_elementary
            logger.info("Building elementary sensor table ...")
            df_elem = self._rebuild_elementary()

            # STEP 5 — analysis_data (57 columns, same schema as WNI)
            logger.info("Building analysis data (57 columns) ...")
            self._write_analysis_data(df_wide, voyage_no=voyage_no)

            # STEP 6 — Append new rows to Excel
            logger.info("Appending new rows to Excel ...")
            exporter = EyegaugeExcelExporter(self.engine)
            exporter.append_new()

            logger.info(
                f"Pipeline complete — {len(df_elem)} rows stored. "
                f"Range: {df_elem['timestamp'].min()} -> {df_elem['timestamp'].max()}"
            )

        except Exception as exc:
            logger.error(f"Pipeline failed: {exc}")
            import traceback; traceback.print_exc()
        finally:
            client.logout()

    # ── STEP 3 ────────────────────────────────────────────────────────────────

    def _build_raw_records(self, df_wide: pd.DataFrame) -> pd.DataFrame:
        df = df_wide.copy()
        df.index.name = "timestamp"
        df = df.reset_index()
        df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)

        # If duplicate timestamps exist across ASSET+DEVICE merge, keep first
        df = df.groupby("timestamp", as_index=False).first()

        sensor_cols = [c for c in df.columns if c != "timestamp"]
        records = []
        for _, row in df.iterrows():
            json_blob = {}
            for col in sensor_cols:
                val = row[col]
                # Safely handle any residual Series or array-like values
                if isinstance(val, pd.Series):
                    val = val.iloc[0] if not val.empty else None
                try:
                    json_blob[col] = None if pd.isna(val) else val
                except (TypeError, ValueError):
                    json_blob[col] = val
            records.append({
                "vessel_name": self.VESSEL_NAME,
                "vessel_imo":  self.VESSEL_IMO,
                "source_id":   self.SOURCE_ID,
                "timestamp":   row["timestamp"],
                "raw_data":    json_blob,
            })

        df_new = pd.DataFrame(records)
        logger.info(f"Built {len(df_new)} new raw records.")
        return df_new

    def _merge_with_existing(self, df_new: pd.DataFrame) -> pd.DataFrame:
        with self.engine.connect() as conn:
            try:
                df_existing = pd.read_sql(
                    "SELECT vessel_name, vessel_imo, source_id, "
                    "timestamp, raw_data FROM raw_eyegauge_logs",
                    conn,
                )
            except Exception:
                df_existing = pd.DataFrame()

        df_combined = pd.concat([df_new, df_existing], ignore_index=True)
        df_combined["raw_data"] = df_combined["raw_data"].apply(to_json_str)
        df_combined = (
            df_combined
            .drop_duplicates(subset=["timestamp"])
            .sort_values("timestamp")
            .reset_index(drop=True)
        )
        return df_combined

    def _write_raw_table(self, df: pd.DataFrame):
        logger.info(f"Storing {len(df)} rows in raw_eyegauge_logs ...")
        with self.engine.begin() as conn:
            conn.execute(
                text("TRUNCATE TABLE raw_eyegauge_logs RESTART IDENTITY CASCADE")
            )
            df.to_sql("raw_eyegauge_logs", conn, if_exists="append", index=False)
        

    # ── STEP 4 ────────────────────────────────────────────────────────────────

    def _rebuild_elementary(self) -> pd.DataFrame:
        with self.engine.connect() as conn:
            df_raw = pd.read_sql(
                "SELECT * FROM raw_eyegauge_logs ORDER BY id ASC", conn
            )

        json_list = (
            df_raw["raw_data"]
            .apply(lambda x: json.loads(x) if isinstance(x, str) else (x or {}))
            .tolist()
        )
        df_sensors = pd.DataFrame(json_list)
        df_sensors.columns = [clean_name(c) for c in df_sensors.columns]

        for col in df_sensors.columns:
            df_sensors[col] = pd.to_numeric(df_sensors[col], errors="coerce")

        df_elem = pd.concat(
            [
                df_raw[["id", "vessel_name", "vessel_imo", "source_id", "timestamp"]],
                df_sensors,
            ],
            axis=1,
        )

        with self.engine.begin() as conn:
            df_elem.to_sql(
                "eyegauge_elementary", conn, if_exists="replace", index=False
            )
            conn.execute(
                text("ALTER TABLE eyegauge_elementary ADD PRIMARY KEY (id)")
            )

        logger.info(f"Elementary table ready — {len(df_elem)} rows, {len(df_sensors.columns)} sensor columns.")
        return df_elem

    # ── STEP 5 ────────────────────────────────────────────────────────────────

    def _write_analysis_data(self, df_wide: pd.DataFrame, voyage_no: str | None = None):

        specs = self._load_vessel_specs()

        existing_ts: set = set()
        with self.engine.connect() as conn:
            try:
                rows = conn.execute(
                    text(
                        'SELECT "Date", "Time_UTC" FROM analysis_data '
                        "WHERE source_id = :sid"
                    ),
                    {"sid": self.SOURCE_ID},
                ).fetchall()
                existing_ts = {(str(r[0]), str(r[1])) for r in rows}
            except Exception:
                logger.info("analysis_data not found yet — all rows will be inserted.")

        df = df_wide.copy()
        df.index.name = "timestamp"
        df = df.reset_index()
        df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)

        analysis_rows = []
        skipped = 0

        for _, row_series in df.iterrows():
            ts = row_series["timestamp"]
            date_str = str(pd.to_datetime(ts).date())
            time_str = pd.to_datetime(ts).strftime("%H:%M")

            if (date_str, time_str) in existing_ts:
                skipped += 1
                continue

            sensor_dict = {}
            for k, v in row_series.drop("timestamp").items():
                if isinstance(v, pd.Series):
                    v = v.iloc[0] if not v.empty else None
                sensor_dict[k] = v
            sensor_dict["__timestamp__"] = ts

            mapped = map_eyegauge_analysis_row(
                row=sensor_dict,
                specs=specs,
                record_id=None,
            )

            mapped["vessel_imo"] = self.VESSEL_IMO
            mapped["source_id"]  = self.SOURCE_ID
            # Inject voyage number fetched from ASSET attributes
            if voyage_no:
                mapped["Voyage_No"] = voyage_no

            analysis_rows.append(clean_dict(mapped))
            existing_ts.add((date_str, time_str))

        logger.info(f"Analysis data — {len(analysis_rows)} new rows, {skipped} already existed.")

        if not analysis_rows:
            logger.info("Analysis data — nothing new to insert.")
            return

        df_analysis = pd.DataFrame(analysis_rows)

        for col in ANALYSIS_DATA_COLUMNS:
            if col not in df_analysis.columns:
                df_analysis[col] = None

        identity_cols = ["vessel_imo", "source_id"]
        ordered_cols  = identity_cols + [
            c for c in ANALYSIS_DATA_COLUMNS if c not in identity_cols
        ]
        df_analysis = df_analysis.reindex(columns=ordered_cols)

        with self.engine.begin() as conn:
            df_analysis.to_sql(
                "analysis_data", conn, if_exists="append", index=False
            )

        logger.info(f"Analysis data saved — {len(df_analysis)} rows.")

    def _load_vessel_specs(self):
        try:
            from models import VesselParticulars
            from database import SessionLocal

            db = SessionLocal()
            try:
                specs = (
                    db.query(VesselParticulars)
                    .filter(VesselParticulars.vessel_imo == self.VESSEL_IMO)
                    .first()
                )
                if not specs:
                    logger.warning(
                        f"No VesselParticulars for IMO {self.VESSEL_IMO}. "
                        "Spec-based columns will use defaults."
                    )
                return specs
            finally:
                db.close()
        except ImportError:
            logger.warning("models/database not importable — spec columns will be NULL.")
            return None

    # ── STEP 6 ────────────────────────────────────────────────────────────────
    # Excel export is handled by EyegaugeExcelExporter in eyegauge_exporter.py


# =============================================================================
# Direct run
# =============================================================================
if __name__ == "__main__":
    pipeline = EyegaugePipeline()
    pipeline.run()