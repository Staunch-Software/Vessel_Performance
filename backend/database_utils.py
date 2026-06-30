import logging
from sqlalchemy import text
from .database import engine
from .models import Base, MariAppsReportData, RawMariAppsLog, AnalysisData, DataQualityLog

log = logging.getLogger(__name__)

def init_mariapps_database():
    Base.metadata.create_all(bind=engine)

    with engine.begin() as conn:
        conn.execute(text("""
            DO $$ BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='analysis_data'
                    AND column_name='raw_report_id'
                    AND is_nullable='NO'
                ) THEN
                    ALTER TABLE analysis_data ALTER COLUMN raw_report_id DROP NOT NULL;
                END IF;
            END $$;
        """))

        conn.execute(text("""
            DO $$ BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='data_quality_logs'
                    AND column_name='raw_report_id'
                    AND is_nullable='NO'
                ) THEN
                    ALTER TABLE data_quality_logs ALTER COLUMN raw_report_id DROP NOT NULL;
                END IF;
            END $$;
        """))

        conn.execute(text("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='analysis_data'
                    AND column_name='raw_mariapps_id'
                ) THEN
                    ALTER TABLE analysis_data ADD COLUMN raw_mariapps_id INTEGER;
                    ALTER TABLE analysis_data ADD CONSTRAINT analysis_data_raw_mariapps_id_fkey
                    FOREIGN KEY (raw_mariapps_id) REFERENCES raw_mariapps_logs(id);
                END IF;
            END $$;
        """))

        conn.execute(text("""
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='data_quality_logs'
                    AND column_name='raw_mariapps_id'
                ) THEN
                    ALTER TABLE data_quality_logs ADD COLUMN raw_mariapps_id INTEGER;
                    ALTER TABLE data_quality_logs ADD CONSTRAINT data_quality_logs_raw_mariapps_id_fkey
                    FOREIGN KEY (raw_mariapps_id) REFERENCES raw_mariapps_logs(id);
                END IF;
            END $$;
        """))

        # CP fair-weather filter needs Beaufort per analysis_data row.
        conn.execute(text("""
            ALTER TABLE analysis_data ADD COLUMN IF NOT EXISTS "BF_Wind" DOUBLE PRECISION;
        """))

        # CP warranty: FO (HFO/LFO) and DO/GO (distillate) per-day warranties (WNI layout).
        conn.execute(text("""
            DO $$ BEGIN
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='vessel_cp_config') THEN
                    ALTER TABLE vessel_cp_config ADD COLUMN IF NOT EXISTS warranted_fo_mtpd   DOUBLE PRECISION;
                    ALTER TABLE vessel_cp_config ADD COLUMN IF NOT EXISTS warranted_dogo_mtpd DOUBLE PRECISION;
                END IF;
            END $$;
        """))

        conn.commit()