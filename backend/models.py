# ============================================================
# DATABASE MODELS MODULE
# ============================================================
# Purpose: Defines all database tables using SQLAlchemy ORM
# 
# Table Structure:
# 1. Vessel - Master vessel registry
# 2. DataSource - Reference table for data providers
# 3. RawNoonReport - Staging layer (raw JSON storage)
# 4. NoonReportData - Normalized 160-column Mari Apps format
# 5. AnalysisData - Performance analysis 57-column format
# 6. DataQualityLog - Audit trail for data issues
# 7. RawMariAppsLog - Staging layer for MariApps
# 8. MariAppsReportData - Normalized 160-column format for MariApps
# ============================================================

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Float, TEXT,Date, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
from pydantic import BaseModel
from datetime import datetime

# Base class for all ORM models
Base = declarative_base()

# ============================================================
# TABLE 1: MASTER VESSEL REGISTRY
# ============================================================
class Vessel(Base):
    __tablename__ = "vessels"
    imo_number = Column(String(20), primary_key=True)
    vessel_id = Column(Integer, nullable=True)
    vessel_name = Column(String(255), nullable=False)

# ============================================================
# TABLE 2: DATA SOURCE REFERENCE
# ============================================================
class DataSource(Base):
    __tablename__ = "data_sources"
    source_id = Column(String(50), primary_key=True)
    source_name = Column(String(100), nullable=False)
    description = Column(TEXT)

# ============================================================
# TABLE 3: RAW NOON REPORTS (WNI STAGING)
# ============================================================
class RawNoonReport(Base):
    __tablename__ = "raw_noon_reports"
    id = Column(Integer, primary_key=True)
    vessel_imo = Column(String(20), ForeignKey("vessels.imo_number"), nullable=False)
    source_id = Column(String(50), ForeignKey("data_sources.source_id"))
    raw_json = Column(JSONB, nullable=False)
    file_name = Column(String(255))
    downloaded_at = Column(DateTime, default=datetime.utcnow)
    fingerprint = Column(String(255), index=True)
    is_duplicate = Column(Boolean, default=False)           

# ============================================================
# TABLE 4: NOON REPORT DATA (WNI 160-COLUMN)
# ============================================================
class NoonReportData(Base):
    __tablename__ = "noon_report_data"
    id = Column(Integer, primary_key=True)
    raw_report_id = Column(Integer, ForeignKey("raw_noon_reports.id"), nullable=False)
    vessel_imo = Column(String(20), ForeignKey("vessels.imo_number", ondelete="CASCADE"), index=True, nullable=False)
    source_id = Column(String(50), ForeignKey("data_sources.source_id"), index=True)

    log_number = Column(String(255), nullable=True)
    validation_status = Column(String(255), nullable=True)
    validation_details = Column(TEXT, nullable=True)
    status = Column(String(255), nullable=True)
    leg_number = Column(String(255), nullable=True)
    to_port = Column(String(255), nullable=True)
    is_closed = Column(Boolean, nullable=True)
    log_date = Column(DateTime, index=True)
    time_zone = Column(String(50), nullable=True)
    log_date_utc = Column(DateTime, nullable=True)
    log_type = Column(String(255), nullable=True)
    loading_condition = Column(String(255), nullable=True)
    log_duration = Column(Float, nullable=True)
    distance_og = Column(Float, nullable=True)
    speed_og = Column(Float, nullable=True)
    distance_to_eosp = Column(Float, nullable=True)
    lat_degree = Column(Float, nullable=True)
    lat_minutes = Column(Float, nullable=True)
    lat_direction = Column(String(255), nullable=True)
    lon_degree = Column(Float, nullable=True)
    lon_minutes = Column(Float, nullable=True)
    lon_direction = Column(String(255), nullable=True)
    cargo_on_board = Column(Float, nullable=True)
    anchorage_hours = Column(String(255), nullable=True)
    drifting_hours = Column(String(255), nullable=True)
    true_wind_force = Column(Float, nullable=True)
    draft_fwd = Column(String(255), nullable=True)
    draft_aft = Column(String(255), nullable=True)
    trim = Column(String(255), nullable=True)
    eta = Column(DateTime, nullable=True)
    etb = Column(DateTime, nullable=True)
    ets = Column(DateTime, nullable=True)
    me1_running_hrs = Column(String(255), nullable=True)
    me1_rpm = Column(String(255), nullable=True)
    me1_power = Column(String(255), nullable=True)
    mcr = Column(String(255), nullable=True)
    ae1_running_hrs = Column(String(255), nullable=True)
    ae1_calculated_e_power = Column(String(255), nullable=True)
    ae1_calc_load = Column(String(255), nullable=True)
    ae2_running_hrs = Column(String(255), nullable=True)
    ae2_calculated_e_power = Column(String(255), nullable=True)
    ae2_calc_load = Column(String(255), nullable=True)
    ae3_running_hrs = Column(String(255), nullable=True)
    ae3_calculated_e_power = Column(String(255), nullable=True)
    ae3_calc_load = Column(String(255), nullable=True)
    bl1_running_hrs = Column(String(255), nullable=True)
    inc1_running_hrs = Column(String(255), nullable=True)
    eg1_running_hrs = Column(String(255), nullable=True)
    combl1_running_hrs = Column(String(255), nullable=True)
    me_total_cons = Column(String(255), nullable=True)
    me_hfo = Column(String(255), nullable=True)
    me_lfo = Column(String(255), nullable=True)
    me_mdo = Column(String(255), nullable=True)
    me_lpg_propane = Column(String(255), nullable=True)
    me_lpg_butane = Column(String(255), nullable=True)
    me_lng = Column(String(255), nullable=True)
    me_methanol = Column(String(255), nullable=True)
    me_ethanol = Column(String(255), nullable=True)
    me_ammonia = Column(String(255), nullable=True)
    me_bio_fuel = Column(String(255), nullable=True)
    ae_total_cons = Column(String(255), nullable=True)
    ae_hfo = Column(String(255), nullable=True)
    ae_lfo = Column(String(255), nullable=True)
    ae_mdo = Column(String(255), nullable=True)
    ae_lpg_propane = Column(String(255), nullable=True)
    ae_lpg_butane = Column(String(255), nullable=True)
    ae_lng = Column(String(255), nullable=True)
    ae_methanol = Column(String(255), nullable=True)
    ae_ethanol = Column(String(255), nullable=True)
    ae_ammonia = Column(String(255), nullable=True)
    ae_bio_fuel = Column(String(255), nullable=True)
    bl_total_cons = Column(String(255), nullable=True)
    bl_hfo = Column(String(255), nullable=True)
    bl_lfo = Column(String(255), nullable=True)
    bl_mdo = Column(String(255), nullable=True)
    bl_lpg_propane = Column(String(255), nullable=True)
    bl_lpg_butane = Column(String(255), nullable=True)
    bl_lng = Column(String(255), nullable=True)
    bl_methanol = Column(String(255), nullable=True)
    bl_ethanol = Column(String(255), nullable=True)
    bl_ammonia = Column(String(255), nullable=True)
    bl_bio_fuel = Column(String(255), nullable=True)
    inc_total_cons = Column(String(255), nullable=True)
    inc_hfo = Column(String(255), nullable=True)
    inc_lfo = Column(String(255), nullable=True)
    inc_mdo = Column(String(255), nullable=True)
    inc_lpg_propane = Column(String(255), nullable=True)
    inc_lpg_butane = Column(String(255), nullable=True)
    inc_lng = Column(String(255), nullable=True)
    inc_methanol = Column(String(255), nullable=True)
    inc_ethanol = Column(String(255), nullable=True)
    inc_ammonia = Column(String(255), nullable=True)
    inc_bio_fuel = Column(String(255), nullable=True)
    eg_total_cons = Column(String(255), nullable=True)
    eg_hfo = Column(String(255), nullable=True)
    eg_lfo = Column(String(255), nullable=True)
    eg_mdo = Column(String(255), nullable=True)
    eg_lpg_propane = Column(String(255), nullable=True)
    eg_lpg_butane = Column(String(255), nullable=True)
    eg_lng = Column(String(255), nullable=True)
    eg_methanol = Column(String(255), nullable=True)
    eg_ethanol = Column(String(255), nullable=True)
    eg_ammonia = Column(String(255), nullable=True)
    eg_bio_fuel = Column(String(255), nullable=True)
    combl_total_cons = Column(String(255), nullable=True)
    combl_hfo = Column(String(255), nullable=True)
    combl_lfo = Column(String(255), nullable=True)
    combl_mdo = Column(String(255), nullable=True)
    combl_lpg_propane = Column(String(255), nullable=True)
    combl_lpg_butane = Column(String(255), nullable=True)
    combl_lng = Column(String(255), nullable=True)
    combl_methanol = Column(String(255), nullable=True)
    combl_ethanol = Column(String(255), nullable=True)
    combl_ammonia = Column(String(255), nullable=True)
    combl_bio_fuel = Column(String(255), nullable=True)
    aeb_total_cons = Column(String(255), nullable=True)
    aeb_hfo = Column(String(255), nullable=True)
    aeb_lfo = Column(String(255), nullable=True)
    aeb_mdo = Column(String(255), nullable=True)
    aeb_lpg_propane = Column(String(255), nullable=True)
    aeb_lpg_butane = Column(String(255), nullable=True)
    aeb_lng = Column(String(255), nullable=True)
    aeb_methanol = Column(String(255), nullable=True)
    aeb_ethanol = Column(String(255), nullable=True)
    aeb_ammonia = Column(String(255), nullable=True)
    aeb_bio_fuel = Column(String(255), nullable=True)
    blfo_total_cons = Column(String(255), nullable=True)
    blfo_hfo = Column(String(255), nullable=True)
    blfo_lfo = Column(String(255), nullable=True)
    blfo_mdo = Column(String(255), nullable=True)
    blfo_lpg_propane = Column(String(255), nullable=True)
    blfo_lpg_butane = Column(String(255), nullable=True)
    blfo_lng = Column(String(255), nullable=True)
    blfo_methanol = Column(String(255), nullable=True)
    blfo_ethanol = Column(String(255), nullable=True)
    blfo_ammonia = Column(String(255), nullable=True)
    blfo_bio_fuel = Column(String(255), nullable=True)
    aft_draught = Column(String(255), nullable=True)
    fore_draught = Column(String(255), nullable=True)
    displacement = Column(Float, nullable=True)
    total_ballast_onboard = Column(Float, nullable=True)
    ship_heading = Column(String(255), nullable=True)
    wind_speed = Column(Float, nullable=True)
    wind_direction = Column(String(255), nullable=True)
    current_speed = Column(String(255), nullable=True)
    current_direction = Column(String(255), nullable=True)
    wave_direction = Column(String(255), nullable=True)
    wave_height = Column(String(255), nullable=True)
    m_e_iso_sfoc = Column(String(255), nullable=True)
    m_e_scoc = Column(String(255), nullable=True)
    apparent_slip = Column(String(255), nullable=True)
    real_slip = Column(String(255), nullable=True)
    a_e_iso_sfoc = Column(String(255), nullable=True)
    nox_emitted = Column(Float, nullable=True)
    co2_emitted = Column(Float, nullable=True)
    sox_emitted = Column(Float, nullable=True)
    eeoi = Column(Float, nullable=True)
    mandatory_failed_reason = Column(TEXT, nullable=True)
    field_validation_failed_reason = Column(TEXT, nullable=True)
    rejected_remarks = Column(TEXT, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

# ============================================================
# TABLE 5: ANALYSIS DATA (SHARED BY WNI & MARIAPPS)
# ============================================================
class AnalysisData(Base):
    __tablename__ = "analysis_data"
    id = Column(Integer, primary_key=True)
    
    # --- MULTI-SOURCE LINKS ---
    # Keep WNI link
    raw_report_id = Column(Integer, ForeignKey("raw_noon_reports.id"), nullable=True)
    # Add MariApps link
    raw_mariapps_id = Column(Integer, ForeignKey("raw_mariapps_logs.id"), nullable=True)
    
    vessel_imo = Column(String(20), ForeignKey("vessels.imo_number", ondelete="CASCADE"), index=True, nullable=False)
    source_id = Column(String(50), ForeignKey("data_sources.source_id"), index=True)

    # --- 57 ANALYSIS COLUMNS ---
    Record_ID = Column(String(255), nullable=True) 
    Date = Column(Date, index=True)
    Time_UTC = Column(String(50))
    Voyage_No = Column(String(255))
    From_Port = Column(String(255))
    To_Port = Column(String(255))
    Loading_Cond = Column(String(50))
    STW_kn = Column(Float)
    SOG_kn = Column(Float)
    Heading_deg = Column(Float)
    Distance_nm = Column(Float)
    Duration_h = Column(Float)
    Draft_Fwd_m = Column(Float)
    Draft_Aft_m = Column(Float)
    Mean_Draft_m = Column(Float)
    Displacement_MT = Column(Float)
    Trim_m = Column(Float)
    ME_Energy_Meter_Reading_KWh = Column(Float)
    Shaft_Power_kW = Column(Float)
    Shaft_RPM = Column(Float)
    ME_COMMON_MASS_FLOWMETER_MT = Column(Float)
    AE_1_ENERGY_READING_KWh = Column(Float)
    A_E_1_RUNNING_HOURS = Column(Float)
    AE_1_POWER_KW = Column(Float)
    AE_2_ENERGY_READING_KWh = Column(Float)
    A_E_2_RUNNING_HOURS = Column(Float)
    AE_2_POWER_KW = Column(Float)
    AE_3_ENERGY_READING_KWh = Column(Float)
    A_E_3_RUNNING_HOURS = Column(Float)
    AE_3_POWER_KW = Column(Float)
    AE_MASS_FLOWMETER_IN = Column(Float)
    AE_FLOWMETER_READING_OUT = Column(Float)
    ME_FOC_MT = Column(Float)
    AE_FOC_MT = Column(Float)
    Est_Power_kW = Column(Float)
    SFOC_gkWh = Column(Float)
    Rel_Wind_Spd_ms = Column(Float)
    Rel_Wind_Dir_deg = Column(Float)
    True_Wind_Spd_ms = Column(Float)
    True_Wind_Dir_deg = Column(Float)
    Sig_Wave_Ht_m = Column(Float)
    Wave_Period_s = Column(Float)
    Wave_Dir_deg = Column(Float)
    Swell_Ht_m = Column(Float)
    Swell_Period_s = Column(Float)
    Swell_Dir_deg = Column(Float)
    Water_Temp_C = Column(Float)
    Water_Depth_m = Column(Float)
    Current_Spd_kn = Column(Float)
    Current_Dir_deg = Column(Float)
    Rudder_Angle_deg = Column(Float)
    P_wind_kW = Column(Float)
    P_wave_kW = Column(Float)
    P_temp_kW = Column(Float)
    VTI = Column(Float)
    Power_Dev_pct = Column(Float)
    Speed_Loss_pct = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)

# ============================================================
# TABLE 6: DATA QUALITY LOG (SHARED)
# ============================================================
class DataQualityLog(Base):
    __tablename__ = "data_quality_logs"
    id = Column(Integer, primary_key=True)
    # Links for both sources
    raw_report_id = Column(Integer, ForeignKey("raw_noon_reports.id"), nullable=True)
    raw_mariapps_id = Column(Integer, ForeignKey("raw_mariapps_logs.id"), nullable=True)
    source_id = Column(String(50), ForeignKey("data_sources.source_id"))
    vessel_name = Column(String(255))
    vessel_imo = Column(String(20))
    issue_type = Column(String(100))
    event_type = Column(String(100))
    report_date = Column(DateTime)
    audit_period = Column(String(100), index=True) 
    created_at = Column(DateTime, default=datetime.utcnow)

# ============================================================
# TABLE 7: RAW MARIAPPS LOG (STAGING)
# ============================================================
class RawMariAppsLog(Base):
    __tablename__ = "raw_mariapps_logs"
    id = Column(Integer, primary_key=True)
    vessel_imo = Column(String(20), ForeignKey("vessels.imo_number"), nullable=True)
    source_id = Column(String(50), ForeignKey("data_sources.source_id"))
    log_number = Column(String(100), index=True)
    leg_number = Column(String(100))
    vessel_name = Column(String(255))
    log_date = Column(String(100))
    log_type = Column(String(100))
    raw_json = Column(JSONB, nullable=False)  
    extracted_at = Column(DateTime, default=datetime.utcnow)
    fingerprint = Column(String(255), index=True)
    is_duplicate = Column(Boolean, default=False)

# ============================================================
# TABLE 8: MARIAPPS REPORT DATA (160-COLUMN)
# ============================================================
class MariAppsReportData(Base):
    __tablename__ = "mariapps_reports_data"
    id = Column(Integer, primary_key=True)
    raw_report_id = Column(Integer, ForeignKey("raw_mariapps_logs.id"), nullable=False)
    vessel_imo = Column(String(20), ForeignKey("vessels.imo_number", ondelete="CASCADE"), index=True, nullable=False)
    source_id = Column(String(50), ForeignKey("data_sources.source_id"), index=True)
    
    # Metadata
    log_number = Column(String(255), index=True)
    validation_status = Column(String(255))
    validation_details = Column(TEXT)
    status = Column(String(255))
    leg_number = Column(String(255))
    to_port = Column(String(255))
    is_closed = Column(Boolean)
    log_date = Column(DateTime, index=True)
    time_zone = Column(String(50))
    log_date_utc = Column(DateTime)
    log_type = Column(String(255))
    loading_condition = Column(String(255))
    log_duration = Column(Float)
    distance_og = Column(Float)
    speed_og = Column(Float)
    distance_to_eosp = Column(Float)
    lat_degree = Column(Float)
    lat_minutes = Column(Float)
    lat_direction = Column(String(10))
    lon_degree = Column(Float)
    lon_minutes = Column(Float)
    lon_direction = Column(String(10))
    cargo_on_board = Column(Float)
    anchorage_hours = Column(String(255))
    drifting_hours = Column(String(255))
    true_wind_force = Column(Float)
    draft_fwd = Column(String(255))
    draft_aft = Column(String(255))
    trim = Column(String(255))
    eta = Column(DateTime)
    etb = Column(DateTime)
    ets = Column(DateTime)
    me1_running_hrs = Column(String(255))
    me1_rpm = Column(String(255))
    me1_power = Column(String(255))
    mcr = Column(String(255))
    ae1_running_hrs = Column(String(255))
    ae1_calculated_e_power = Column(String(255))
    ae1_calc_load = Column(String(255))
    ae2_running_hrs = Column(String(255))
    ae2_calculated_e_power = Column(String(255))
    ae2_calc_load = Column(String(255))
    ae3_running_hrs = Column(String(255))
    ae3_calculated_e_power = Column(String(255))
    ae3_calc_load = Column(String(255))
    bl1_running_hrs = Column(String(255))
    inc1_running_hrs = Column(String(255))
    eg1_running_hrs = Column(String(255))
    combl1_running_hrs = Column(String(255))
    me_total_cons = Column(String(255))
    me_hfo = Column(String(255))
    me_lfo = Column(String(255))
    me_mdo = Column(String(255))
    me_lpg_propane = Column(String(255))
    me_lpg_butane = Column(String(255))
    me_lng = Column(String(255))
    me_methanol = Column(String(255))
    me_ethanol = Column(String(255))
    me_ammonia = Column(String(255))
    me_bio_fuel = Column(String(255))
    ae_total_cons = Column(String(255))
    ae_hfo = Column(String(255))
    ae_lfo = Column(String(255))
    ae_mdo = Column(String(255))
    ae_lpg_propane = Column(String(255))
    ae_lpg_butane = Column(String(255))
    ae_lng = Column(String(255))
    ae_methanol = Column(String(255))
    ae_ethanol = Column(String(255))
    ae_ammonia = Column(String(255))
    ae_bio_fuel = Column(String(255))
    bl_total_cons = Column(String(255))
    bl_hfo = Column(String(255))
    bl_lfo = Column(String(255))
    bl_mdo = Column(String(255))
    bl_lpg_propane = Column(String(255))
    bl_lpg_butane = Column(String(255))
    bl_lng = Column(String(255))
    bl_methanol = Column(String(255))
    bl_ethanol = Column(String(255))
    bl_ammonia = Column(String(255))
    bl_bio_fuel = Column(String(255))
    inc_total_cons = Column(String(255))
    inc_hfo = Column(String(255))
    inc_lfo = Column(String(255))
    inc_mdo = Column(String(255))
    inc_lpg_propane = Column(String(255))
    inc_lpg_butane = Column(String(255))
    inc_lng = Column(String(255))
    inc_methanol = Column(String(255))
    inc_ethanol = Column(String(255))
    inc_ammonia = Column(String(255))
    inc_bio_fuel = Column(String(255))
    eg_total_cons = Column(String(255))
    eg_hfo = Column(String(255))
    eg_lfo = Column(String(255))
    eg_mdo = Column(String(255))
    eg_lpg_propane = Column(String(255))
    eg_lpg_butane = Column(String(255))
    eg_lng = Column(String(255))
    eg_methanol = Column(String(255))
    eg_ethanol = Column(String(255))
    eg_ammonia = Column(String(255))
    eg_bio_fuel = Column(String(255))
    combl_total_cons = Column(String(255))
    combl_hfo = Column(String(255))
    combl_lfo = Column(String(255))
    combl_mdo = Column(String(255))
    combl_lpg_propane = Column(String(255))
    combl_lpg_butane = Column(String(255))
    combl_lng = Column(String(255))
    combl_methanol = Column(String(255))
    combl_ethanol = Column(String(255))
    combl_ammonia = Column(String(255))
    combl_bio_fuel = Column(String(255))
    aeb_total_cons = Column(String(255))
    aeb_hfo = Column(String(255))
    aeb_lfo = Column(String(255))
    aeb_mdo = Column(String(255))
    aeb_lpg_propane = Column(String(255))
    aeb_lpg_butane = Column(String(255))
    aeb_lng = Column(String(255))
    aeb_methanol = Column(String(255))
    aeb_ethanol = Column(String(255))
    aeb_ammonia = Column(String(255))
    aeb_bio_fuel = Column(String(255))
    blfo_total_cons = Column(String(255))
    blfo_hfo = Column(String(255))
    blfo_lfo = Column(String(255))
    blfo_mdo = Column(String(255))
    blfo_lpg_propane = Column(String(255))
    blfo_lpg_butane = Column(String(255))
    blfo_lng = Column(String(255))
    blfo_methanol = Column(String(255))
    blfo_ethanol = Column(String(255))
    blfo_ammonia = Column(String(255))
    blfo_bio_fuel = Column(String(255))
    aft_draught = Column(String(255))
    fore_draught = Column(String(255))
    displacement = Column(Float)
    total_ballast_onboard = Column(Float)
    ship_heading = Column(String(255))
    wind_speed = Column(Float)
    wind_direction = Column(String(255))
    current_speed = Column(String(255))
    current_direction = Column(String(255))
    wave_height = Column(String(255))
    wave_direction = Column(String(255))
    m_e_iso_sfoc = Column(String(255))
    m_e_scoc = Column(String(255))
    apparent_slip = Column(String(255))
    real_slip = Column(String(255))
    a_e_iso_sfoc = Column(String(255))
    nox_emitted = Column(Float)
    co2_emitted = Column(Float)
    sox_emitted = Column(Float)
    eeoi = Column(Float)
    mandatory_failed_reason = Column(TEXT)
    field_validation_failed_reason = Column(TEXT)
    rejected_remarks = Column(TEXT)
    created_at = Column(DateTime, default=datetime.utcnow)

# ============================================================
# TABLE 9: EXPANDED COLUMN METADATA
# ============================================================
class ExpandedColumnMetadata(Base):
    """
    Stores display metadata for every column in expanded_mariapps_data
    and expanded_wni_data. Drives the frontend column picker.
    """
    __tablename__ = "expanded_column_metadata"
    id           = Column(Integer, primary_key=True)
    source       = Column(String(20),  nullable=False)   # 'mari_apps' | 'wni'
    db_column    = Column(String(100), nullable=False)   # actual PostgreSQL column name
    display_name = Column(String(300))                   # Category_Name_Operational_LF
    category     = Column(String(200))                   # from xlsx
    unit         = Column(String(50))
    description  = Column(TEXT)
    is_active    = Column(Boolean, default=True)         # yellow=True, pink=False
    is_identity  = Column(Boolean, default=False)        # id/date/vessel cols
    performance  = Column(Boolean, default=False)        # performance-relevant column flag
    sort_order   = Column(Integer, default=0)

    # Matches the ON CONFLICT (source, db_column) upsert in pipeline/expander.py.
    # Without this, Base.metadata.create_all() builds the table with no matching
    # unique constraint and the metadata upsert fails on a fresh database.
    __table_args__ = (
        UniqueConstraint("source", "db_column", name="uq_expanded_col_source_dbcol"),
    )

class VesselParticulars(Base):
    """
    Stores the static technical specifications extracted from 
    vessel documents (Particulars, EEXI files, Sea Trials).
    
    This data serves as the baseline for performance analysis.
    """
    __tablename__ = "vessel_particulars"

    # Link to the Master Vessel Registry
    vessel_imo = Column(String(20), ForeignKey("vessels.imo_number", ondelete="CASCADE"), primary_key=True)
    
    # Identification & Registry
    flag = Column(String(100))
    vessel_type = Column(String(100))
    year_built = Column(Integer)
    classification_society = Column(String(100))

    # Principal Dimensions (Stored as Floats for calculations)
    length_overall = Column(Float)              # LOA [m]
    length_bp = Column(Float)                   # LBP [m]
    beam = Column(Float)                        # Breadth [m]
    design_draft = Column(Float)                # T_design [m]
    deadweight = Column(Float)                  # DWT [MT]

    # Main Engine (ME)
    me_engine_type = Column(String(255))
    me_engine_mcr_kw = Column(Float)            # MCR in kW
    
    # Auxiliary Engine (AE)
    ae_engine_type = Column(String(255))
    ae_engine_mcr_kw = Column(Float)            # MCR in kW (per unit)

    # Baseline Events & Maintenance
    sea_trial_date = Column(DateTime, nullable=True)
    last_drydock_date = Column(DateTime, nullable=True)
    coating_type = Column(String(255), nullable=True)

    # --- Vessel Identification ---
    call_sign = Column(String(50), nullable=True)                        # Call Sign

    # --- Principal Dimensions ---
    depth_m = Column(Float, nullable=True)                               # Depth (D) [m]
    scantling_draft = Column(Float, nullable=True)                       # Scantling Draft [m]
    ballast_draft_mean = Column(Float, nullable=True)                    # Ballast Draft Mean [m]
    block_coefficient_cb = Column(Float, nullable=True)                  # Block Coefficient (Cb)
    waterplane_coefficient_cwp = Column(Float, nullable=True)            # Waterplane Coefficient (Cwp)

    # --- Hull Form Parameters (for Weather Corrections) ---
    wetted_surface_area_design = Column(Float, nullable=True)            # Wetted Surface Area at Design Draft [m²]
    wetted_surface_area_ballast = Column(Float, nullable=True)           # Wetted Surface Area at Ballast Draft [m²]
    transverse_projected_area = Column(Float, nullable=True)             # Transverse Projected Area Above WL (A_XV) [m²]
    lateral_projected_area_lv = Column(Float, nullable=True)             # Lateral Projected Area Above WL (A_LV) [m²]
    lateral_area_superstructure = Column(Float, nullable=True)           # Lateral Area of Superstructure (A_OD) [m²]
    height_wl_to_center_lateral = Column(Float, nullable=True)           # Height from WL to Center of Lateral Area (H_C) [m]
    height_top_superstructure = Column(Float, nullable=True)             # Height of Top of Superstructure (H_BR) [m]
    distance_midship_to_center_lateral = Column(Float, nullable=True)    # Distance Midship to Center of Lateral Area (C_MC) [m]

    # --- Displacement & Capacity ---
    lightship_weight = Column(Float, nullable=True)                      # Lightship Weight [MT]
    displacement_at_design = Column(Float, nullable=True)                # Displacement at Design Draft [MT]
    displacement_at_scantling = Column(Float, nullable=True)             # Displacement at Scantling Draft [MT]
    displacement_at_ballast = Column(Float, nullable=True)               # Displacement at Ballast [MT]
    tpc_at_design = Column(Float, nullable=True)                         # TPC at Design [MT/cm]
    lcf_from_midship = Column(Float, nullable=True)                      # LCF from Midship [m]
    mct = Column(Float, nullable=True)                                   # MCT (Moment to Change Trim 1cm) [MT-m]
    gross_tonnage = Column(Float, nullable=True)                         # Gross Tonnage (GT)

    # --- Main Engine (extended) ---
    me_mcr_rpm = Column(Float, nullable=True)                            # Engine MCR RPM
    ncr_kw = Column(Float, nullable=True)                                # NCR [kW]
    ncr_rpm = Column(Float, nullable=True)                               # NCR RPM
    sfoc_at_ncr = Column(Float, nullable=True)                           # SFOC at NCR [g/kWh]
    propeller_law_exponent = Column(Float, nullable=True)                # Propeller Law Exponent

    # --- Auxiliary Engine (extended) ---
    ae_number_of_units = Column(Integer, nullable=True)                  # Number of AE Units
    ae_sfoc_at_75_load = Column(Float, nullable=True)                    # AE SFOC at 75% Load [g/kWh]

    # --- Propeller ---
    propeller_type = Column(String(50), nullable=True)                   # Propeller Type (FPP/CPP)
    propeller_diameter = Column(Float, nullable=True)                    # Propeller Diameter [m]
    number_of_blades = Column(Integer, nullable=True)                    # Number of Blades
    design_pitch = Column(Float, nullable=True)                          # Design Pitch [m]
    expanded_area_ratio = Column(Float, nullable=True)                   # Expanded Area Ratio (EAR)

    # --- Baseline Power Curve Coefficients ---
    baseline_coeff_a_laden = Column(Float, nullable=True)                # Baseline Coefficient A (Laden)
    baseline_exponent_n_laden = Column(Float, nullable=True)             # Baseline Exponent n (Laden)
    reference_draft_laden = Column(Float, nullable=True)                 # Reference Draft (Laden) [m]
    baseline_coeff_a_ballast = Column(Float, nullable=True)              # Baseline Coefficient A (Ballast)
    baseline_exponent_n_ballast = Column(Float, nullable=True)           # Baseline Exponent n (Ballast)
    reference_draft_ballast = Column(Float, nullable=True)               # Reference Draft (Ballast) [m]

    # --- Propulsion Efficiency Factors ---
    hull_efficiency = Column(Float, nullable=True)                       # Hull Efficiency (η_H)
    relative_rotative_efficiency = Column(Float, nullable=True)          # Relative Rotative Efficiency (η_R)
    open_water_efficiency = Column(Float, nullable=True)                 # Open Water Efficiency (η_O)
    transmission_efficiency = Column(Float, nullable=True)               # Transmission Efficiency (η_S)
    total_propulsive_efficiency = Column(Float, nullable=True)           # Total Propulsive Efficiency (η_T)

    # --- Wind Resistance Coefficients (ISO 15016) ---
    wind_coeff_cx_0 = Column(Float, nullable=True)                       # C_X at 0° (head wind)
    wind_coeff_cx_30 = Column(Float, nullable=True)                      # C_X at 30°
    wind_coeff_cx_60 = Column(Float, nullable=True)                      # C_X at 60°
    wind_coeff_cx_90 = Column(Float, nullable=True)                      # C_X at 90° (beam)
    wind_coeff_cx_120 = Column(Float, nullable=True)                     # C_X at 120°
    wind_coeff_cx_150 = Column(Float, nullable=True)                     # C_X at 150°
    wind_coeff_cx_180 = Column(Float, nullable=True)                     # C_X at 180° (following)

    # --- Baseline Events (extended) ---
    last_hull_inspection_date = Column(DateTime, nullable=True)          # Last Hull Inspection Date
    last_hull_cleaning_date = Column(DateTime, nullable=True)            # Last Hull Cleaning Date
    last_propeller_polishing_date = Column(DateTime, nullable=True)      # Last Propeller Polishing Date

    # --- ISO 19030 Filter Thresholds ---
    max_true_wind_speed = Column(Float, nullable=True)                   # Max True Wind Speed [m/s]
    max_sig_wave_height = Column(Float, nullable=True)                   # Max Significant Wave Height [m]
    max_current_speed = Column(Float, nullable=True)                     # Max Current Speed [kn]
    min_water_depth_factor = Column(Float, nullable=True)                # Min Water Depth Factor x Mean Draft
    min_absolute_water_depth = Column(Float, nullable=True)              # Min Absolute Water Depth [m]
    max_rudder_angle = Column(Float, nullable=True)                      # Max Rudder Angle [deg]
    speed_range_from_baseline = Column(Float, nullable=True)             # Speed Range from Baseline [±kn]
    max_env_power_ratio = Column(Float, nullable=True)                   # Max Environmental Power Ratio (β)

    # --- Measurement Equipment Flags ---
    me_shaft_power_meter = Column(Boolean, nullable=True)                # ME Shaft Power Meter Present?
    me_mass_flowmeter = Column(Boolean, nullable=True)                   # ME Mass Flowmeter Present?
    ae_energy_meter = Column(Boolean, nullable=True)                     # AE Energy Meter Present?
    ae_mass_flowmeter = Column(Boolean, nullable=True)                   # AE Mass Flowmeter Present?
    speed_log_type = Column(String(100), nullable=True)                  # Speed Log Type
    wave_data_source = Column(String(100), nullable=True)

    # Audit Fields
    extracted_at = Column(DateTime, default=datetime.utcnow)
    source_file = Column(String(255))

class VesselParticularsResponse(BaseModel):
    # CHANGE ALL SQLALCHEMY TYPES TO STANDARD PYTHON TYPES:
    vessel_imo: str  # Was String(20)
    flag: str        # Was String(100)
    vessel_type: str # Was String(100)
    year_built: int  # Was Integer
    length_overall: float # Was Float
    beam: float            # Was Float
    design_draft: float    # Was Float
    deadweight: float      # Was Float
    me_engine_type: str    # Was String(255)
    me_engine_mcr_kw: float # Was Float
    ae_engine_type: str    # Was String(255)
    ae_engine_mcr_kw: float # Was Float
    
    # Dates must be standard datetime or str
    sea_trial_date: datetime | None = None 
    last_drydock_date: datetime | None = None
    last_hull_inspection_date: datetime | None = None
    last_hull_cleaning_date: datetime | None = None
    
    # ... other fields must also be converted ...
    
    model_config = {
        'from_attributes': True
    }

# ============================================================
# TABLE: VESSEL DESIGN DATA (MDM — Master Data Management)
# ============================================================
# Stores 502 design/specification fields per vessel.
# Column naming convention: CategoryShortCode_Symbol_design_data
# Source: mdm_column_mapping.xlsx
# ============================================================
class VesselDesignData(Base):
    __tablename__ = "vessel_design_data"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    vessel_imo = Column(String(20), ForeignKey("vessels.imo_number", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    ModelingStatus_HPVerModel_design_data = Column(TEXT, nullable=True)  # Verified HP Model — *
    ModelingStatus_MEVerModel_design_data = Column(TEXT, nullable=True)  # Verified ME Model — *
    ModelingStatus_AEVerModel_design_data = Column(TEXT, nullable=True)  # Verified AE Model — *
    ModelingStatus_NoonVerModel_design_data = Column(TEXT, nullable=True)  # Verified Noon Model — *
    ModelingStatus_HPLogConfig_design_data = Column(TEXT, nullable=True)  # HP Log Configuration
    ModelingStatus_MELogConfig_design_data = Column(TEXT, nullable=True)  # ME Log Configuration
    ModelingStatus_AELogConfig_design_data = Column(TEXT, nullable=True)  # AE Log Configuration
    ModelingStatus_NoonLogConfig_design_data = Column(TEXT, nullable=True)  # Noon Log Configuration
    ShipParticulars_HullNoVessel_design_data = Column(TEXT, nullable=True)  # Hull No
    ShipParticulars_IMONoVessel_design_data = Column(Float, nullable=True)  # IMO No
    ShipParticulars_BuildYardVessel_design_data = Column(TEXT, nullable=True)  # Build Yard
    ShipParticulars_YearBuildVessel_design_data = Column(TEXT, nullable=True)  # Year Build
    ShipParticulars_UltimateOwnerVessel_design_data = Column(TEXT, nullable=True)  # Ultimate Owner
    ShipParticulars_ClassificationSocietyVessel_design_data = Column(TEXT, nullable=True)  # Classification Society
    ShipParticulars_TypeVessel_design_data = Column(TEXT, nullable=True)  # Vessel Type
    ShipParticulars_TypeSTAWINDVessel_design_data = Column(TEXT, nullable=True)  # Vessel Type as per STAWIND Method — **
    ShipParticulars_SuperStructureSTAWINDVessel_design_data = Column(TEXT, nullable=True)  # Superstructre Type as per STAWIND Method — **
    ShipParticulars_EuMrvVesselType_design_data = Column(TEXT, nullable=True)  # Vessel Type as per EU MRV — *
    ShipParticulars_Loa_design_data = Column(Float, nullable=True)  # Length Overall [m]
    ShipParticulars_Lbp_design_data = Column(Float, nullable=True)  # Length Between Perpendiculars [m] — **
    ShipParticulars_B_design_data = Column(Float, nullable=True)  # Moulded Breadth [m] — **
    ShipParticulars_D_design_data = Column(Float, nullable=True)  # Moulded Depth [m] — *
    ShipParticulars_Td_design_data = Column(Float, nullable=True)  # Design Draught [m] — **
    ShipParticulars_Tb_design_data = Column(Float, nullable=True)  # Ballast Reference Draught [m] — **
    ShipParticulars_Ts_design_data = Column(Float, nullable=True)  # Summer/Scantling Draught [m] — **
    ShipParticulars_Ud_design_data = Column(Float, nullable=True)  # Design Speed [kn] — *
    ShipParticulars_CapacityCargoVessel_design_data = Column(Float, nullable=True)  # Cargo Hold/Tank Volume (100%) [TEU]
    ShipParticulars_DWT_design_data = Column(Float, nullable=True)  # Deadweight at Scantling Draught [MT] — *
    ShipParticulars_nCHVessel_design_data = Column(Float, nullable=True)  # Number of cargo Holds/Tanks
    ShipParticulars_TypeCGVessel_design_data = Column(TEXT, nullable=True)  # Cargo Gear Type
    ShipParticulars_nCGVessel_design_data = Column(Float, nullable=True)  # Number of Cargo Gear
    ShipParticulars_CapacityCGVessel_design_data = Column(Float, nullable=True)  # Cargo Gear Capacity
    ShipParticulars_Ds_design_data = Column(Float, nullable=True)  # Scantling Mass Total Displacement [MT] — *
    ShipParticulars_Vs_design_data = Column(Float, nullable=True)  # Scantling Volume Moulded Displacement [m3]
    ShipParticulars_Dd_design_data = Column(Float, nullable=True)  # Design Mass Total Displacement [MT]
    ShipParticulars_Vd_design_data = Column(Float, nullable=True)  # Design Volume Moulded Displacement [m3]
    ShipParticulars_Ad_design_data = Column(Float, nullable=True)  # Transverse Projected Area Above Design Draught [m2] — **
    ShipParticulars_Zad_design_data = Column(Float, nullable=True)  # Anemometer Height Above Design Draught [m] — **
    ShipParticulars_BulbousBowVessel_design_data = Column(TEXT, nullable=True)  # Bulbous Bow — **
    ShipParticulars_nISBRG_design_data = Column(Float, nullable=True)  # Number of Intermediate Shaft Bearing
    ShipParticulars_etaS_design_data = Column(Float, nullable=True)  # Shaft Efficiency (etaS=PD/PS) — *
    ShipParticulars_etaB_design_data = Column(Float, nullable=True)  # Bearing Efficiency (etaB=PS/PB)
    ShipParticulars_AutoLoggingVessel_design_data = Column(TEXT, nullable=True)  # Auto-Logging Installed
    ShipParticulars_AutoLoggingMakerVessel_design_data = Column(TEXT, nullable=True)  # Auto-Logging Maker
    ShipParticulars_DrawingURLVessel_design_data = Column(TEXT, nullable=True)  # Drawing SharePoint URL
    ShipParticulars_SM_design_data = Column(Float, nullable=True)  # Sea Margin Percentage [%]
    ShipParticulars_GT_design_data = Column(Float, nullable=True)  # Gross Tonnage of Vessel [MT]
    ShipParticulars_BowSection_design_data = Column(TEXT, nullable=True)  # Bulbous Bow Section at Fore Perpendicular [m]
    ShipParticulars_Cstern_design_data = Column(TEXT, nullable=True)  # Stern Shape Parameter — **
    ShipParticulars_TransomSternVessel_design_data = Column(TEXT, nullable=True)  # Transom Stern — **
    ShipParticulars_HullProfile_design_data = Column(TEXT, nullable=True)  # Hull Profile [m] — **
    ShipParticulars_RudderProfile_design_data = Column(TEXT, nullable=True)  # Rudder Profile [m] — **
    ShipParticulars_TransomSection_design_data = Column(TEXT, nullable=True)  # Transom Section [m] — **
    ShipParticulars_vesselwp_design_data = Column(TEXT, nullable=True)  # External weather provider — **
    ShipParticulars_CargoPage_design_data = Column(TEXT, nullable=True)  # Calibrated Cargo Module for LPG Vessel
    ShipParticulars_TypeWeathermodelVessel_design_data = Column(TEXT, nullable=True)  # Vessel Type as per DTN Models
    ShipParticulars_LiqMan_design_data = Column(TEXT, nullable=True)  # Liquid Mainfold
    ShipParticulars_VapMan_design_data = Column(TEXT, nullable=True)  # Vapour Manifold
    ShipParticulars_CargoConst_design_data = Column(TEXT, nullable=True)  # Cargo Constant
    ShipParticulars_CargoDelta_design_data = Column(TEXT, nullable=True)  # Cargo Delta
    ShipParticulars_LNGBunkerCapability_design_data = Column(TEXT, nullable=True)  # Is LNG bunkered as fuel?
    ShipParticulars_vesselsensd_design_data = Column(TEXT, nullable=True)  # Vessel Sensor data provider
    ShipParticulars_CapacityTEUVessel_design_data = Column(Float, nullable=True)  # Nominal TEU Capacity [TEU]
    ShipParticulars_Biobunkcap_design_data = Column(TEXT, nullable=True)  # Biofuel bunkering capability
    ShipParticulars_DesignBOR_design_data = Column(Float, nullable=True)  # Design Boil off Rate [%/day]
    ShipParticulars_CapacitylngVessel_design_data = Column(Float, nullable=True)  # LNG Cargo Capacity excluding Dome [m3]
    ShipParticulars_DOTANKCAP_design_data = Column(TEXT, nullable=True)  # Diesel oil tank capacity [MT]
    ShipParticulars_LNGTANKCAP_design_data = Column(TEXT, nullable=True)  # Gas tank capacity [MT]
    ShipParticulars_OTHERTANKCAP_design_data = Column(TEXT, nullable=True)  # Other tank capacity [MT]
    ShipParticulars_FOTANKCAP_design_data = Column(TEXT, nullable=True)  # Fuel oil tank capacity [MT]
    ShipHydrostatics_rhoswh_design_data = Column(Float, nullable=True)  # Water Density of Hydrostatic Data [kg/m3] — **
    ShipHydrostatics_Th_design_data = Column(TEXT, nullable=True)  # Hydrostatics Reference Draught [m] — **
    ShipHydrostatics_Dh_design_data = Column(TEXT, nullable=True)  # Mass Total Displacement at Reference Draught [MT] — **
    ShipHydrostatics_WSAh_design_data = Column(TEXT, nullable=True)  # Wetted Surface Area at Reference Draught [m2]
    ShipHydrostatics_Cmh_design_data = Column(TEXT, nullable=True)  # Midship Section Coefficient at Reference Draught
    ShipHydrostatics_Cwph_design_data = Column(TEXT, nullable=True)  # Waterplane Area Coefficient at Reference Draught
    ShipHydrostatics_LCBh_design_data = Column(TEXT, nullable=True)  # Longitudinal Centre of Buoyancy at Reference Draught [m]
    ModelTest_TaMT_design_data = Column(TEXT, nullable=True)  # Aft Draught for All Loading Conditions During Model Tests [m] — **
    ModelTest_TfMT_design_data = Column(TEXT, nullable=True)  # Fore Draught for All Loading Conditions during Model Tests [m] — **
    ModelTest_VMT_design_data = Column(TEXT, nullable=True)  # Volume Displacement for All Loading Conditions during Model Tests [m3] — **
    ModelTest_PowerTypeMT_design_data = Column(TEXT, nullable=True)  # Power Type in Model Tests — **
    ModelTest_U0MT_design_data = Column(TEXT, nullable=True)  # Speed at 0% SM for All Loading Conditions during Model Tests [kn] — **
    ModelTest_P0MT_design_data = Column(TEXT, nullable=True)  # Power at 0% SM for All Loading Conditions during Model Tests [kW] — **
    ModelTest_N0MT_design_data = Column(TEXT, nullable=True)  # Propeller Rotational Speed at 0% SM for All Loading Conditions during Model Tests [RPM] — **
    ModelTest_etaD0MT_design_data = Column(TEXT, nullable=True)  # Propulsive Efficiency at 0% SM for All Loading Conditions during Model Tests
    ModelTest_U15MT_design_data = Column(TEXT, nullable=True)  # Speed at 15% SM for All Loading Conditions during Model Tests [kn]
    ModelTest_P15MT_design_data = Column(TEXT, nullable=True)  # Power at 15% SM for All Loading Conditions during Model Tests [kW]
    ModelTest_N15MT_design_data = Column(TEXT, nullable=True)  # Propeller Rotational Speed at 15% SM for All Loading Conditions during Model Tests [RPM]
    ModelTest_etaD15MT_design_data = Column(TEXT, nullable=True)  # Propulsive Efficiency at 15% SM for All Loading Conditions during Model Tests
    ModelTest_TrialIndexMT_design_data = Column(Float, nullable=True)  # Trial Loading Condition Index Among the Given Ones — **
    ModelTest_UtrialMT_design_data = Column(TEXT, nullable=True)  # Model Test Speed Data at Trial Condition as Shown on Sea Trials Report [kn] — **
    ModelTest_PtrialMT_design_data = Column(TEXT, nullable=True)  # Model Test Power Data at Trial Condition as Shown on Sea Trials Report [kW] — **
    ModelTest_NtrialMT_design_data = Column(TEXT, nullable=True)  # Model Test Propeller Rotational Speed Data at Trial Condition as Shown on Sea Trials Report [RPM] — **
    ModelTest_MT_design_data = Column(TEXT, nullable=True)  # Model Test Report Availability — **
    Propeller_nProp_design_data = Column(Float, nullable=True)  # Number of Propellers — **
    Propeller_TypeProp_design_data = Column(TEXT, nullable=True)  # Propeller Type — **
    Propeller_dProp_design_data = Column(Float, nullable=True)  # Propeller Diameter [m] — **
    Propeller_pitchProp_design_data = Column(Float, nullable=True)  # Propeller Pitch (at 0.7R) [m] — **
    Propeller_zProp_design_data = Column(Integer, nullable=True)  # Number of Propeller Blades
    Propeller_AeAoProp_design_data = Column(Float, nullable=True)  # Propeller Expanded Area Ratio
    SeaTrialsHull_HullNoSTrial_design_data = Column(TEXT, nullable=True)  # Hull No of the Selected Sea Trials Report
    SeaTrialsHull_PowerTypeSTrial_design_data = Column(TEXT, nullable=True)  # Power Type in Sea Trials — **
    SeaTrialsHull_TaConSTrial_design_data = Column(Float, nullable=True)  # Contract Aft Draught during Sea Trials [m] — **
    SeaTrialsHull_TfConSTrial_design_data = Column(Float, nullable=True)  # Contract Fore Draught during Sea Trials [m] — **
    SeaTrialsHull_VConSTrial_design_data = Column(Float, nullable=True)  # Contract Volume Displacement during Sea Trials [m3] — **
    SeaTrialsHull_TaSTrial_design_data = Column(Float, nullable=True)  # Aft Draught during Sea Trials [m] — **
    SeaTrialsHull_TfSTrial_design_data = Column(Float, nullable=True)  # Fore Draught during Sea Trials [m] — **
    SeaTrialsHull_VSTrial_design_data = Column(Float, nullable=True)  # Volume Displacement during Sea Trials [m3] — **
    SeaTrialsHull_UCorSTrial_design_data = Column(TEXT, nullable=True)  # Speed Data from Sea Trial Analysis Corrected for Contract Weather and Loading Conditions [kn] — **
    SeaTrialsHull_PCorSTrial_design_data = Column(TEXT, nullable=True)  # Power Data from Sea Trial Analysis Corrected for Contract Weather and Loading Conditions [kW] — **
    SeaTrialsHull_NCorSTrial_design_data = Column(TEXT, nullable=True)  # Propeller Rotational Speed Data from Sea Trial Analysis Corrected for Contract Weather and Loading Conditions [RPM] — **
    SeaTrialsHullCorrection_WeatherCorSTrial_design_data = Column(TEXT, nullable=True)  # Sea Trials Analysis has been performed
    SeaTrialsHullCorrection_TEUSTrial_design_data = Column(TEXT, nullable=True)  # Containers on Main Deck during Sea Trials
    SeaTrialsHullCorrection_WSASTrial_design_data = Column(Float, nullable=True)  # Wetted Surface Area during Sea Trials [m2]
    SeaTrialsHullCorrection_TswSTrial_design_data = Column(Float, nullable=True)  # Water Temperature during Sea Trials [°C]
    SeaTrialsHullCorrection_rhoswSTrial_design_data = Column(Float, nullable=True)  # Water Density during Sea Trials [kg/m3]
    SeaTrialsHullCorrection_TairSTrial_design_data = Column(Float, nullable=True)  # Atmospheric Air Temperature during Sea Trials [°C]
    SeaTrialsHullCorrection_pairSTrial_design_data = Column(Float, nullable=True)  # Atmospheric Air Pressure during Sea Trials [mbar]
    SeaTrialsHullCorrection_azbowSTrial_design_data = Column(TEXT, nullable=True)  # Pitch or Heave Motions during Sea Trials
    SeaTrialsHullCorrection_SOGSTrial_design_data = Column(TEXT, nullable=True)  # Measured Speed Over Ground during Sea Trials [kn]
    SeaTrialsHullCorrection_PSTrial_design_data = Column(TEXT, nullable=True)  # Measured Power during Sea Trials [kW]
    SeaTrialsHullCorrection_NPropSTrial_design_data = Column(TEXT, nullable=True)  # Measured Propeller Rotational Speed during Sea Trials [RPM]
    SeaTrialsHullCorrection_HeadSTrial_design_data = Column(TEXT, nullable=True)  # Ship Heading during Sea Trials [deg]
    SeaTrialsHullCorrection_UwirSTrial_design_data = Column(TEXT, nullable=True)  # Relative Wind Speed at Anemometer Height during Sea Trials [kn]
    SeaTrialsHullCorrection_psiwirSTrial_design_data = Column(TEXT, nullable=True)  # Relative Wind Direction at Anemometer Height during Sea Trials [deg]
    SeaTrialsHullCorrection_HwvSTrial_design_data = Column(TEXT, nullable=True)  # Wave Height during Sea Trials [m]
    SeaTrialsHullCorrection_TwvSTrial_design_data = Column(TEXT, nullable=True)  # Wave Period during Sea Trials [s]
    SeaTrialsHullCorrection_psiwvrSTrial_design_data = Column(TEXT, nullable=True)  # Relative Wave Direction during Sea Trials [deg]
    SeaTrialsHullCorrection_HslSTrial_design_data = Column(TEXT, nullable=True)  # Swell Height during Sea Trials [m]
    SeaTrialsHullCorrection_TslSTrial_design_data = Column(TEXT, nullable=True)  # Swell Period during Sea Trials [s]
    SeaTrialsHullCorrection_psislrSTrial_design_data = Column(TEXT, nullable=True)  # Relative Swell Direction during Sea Trials [deg]
    SeaTrialsHullCorrection_hswSTrial_design_data = Column(TEXT, nullable=True)  # Water Depth during Sea Trials [m]
    ME_nME_design_data = Column(Integer, nullable=True)  # Number of MEs
    ME_MakerME_design_data = Column(TEXT, nullable=True)  # ME Maker
    ME_BuilderME_design_data = Column(TEXT, nullable=True)  # ME Licensee/Builder
    ME_ModelME_design_data = Column(TEXT, nullable=True)  # ME Model
    ME_SerNoME_design_data = Column(TEXT, nullable=True)  # ME Serial No
    ME_CategoryME_design_data = Column(TEXT, nullable=True)  # ME Category — ***
    ME_TypeME_design_data = Column(TEXT, nullable=True)  # ME Type
    ME_ModeME_design_data = Column(TEXT, nullable=True)  # ME Modes
    ME_ME_Consumer_Class_design_data = Column(TEXT, nullable=True)  # Main Engine Consumer Class
    ME_ncME_design_data = Column(Integer, nullable=True)  # ME Number of Cylinders — ***
    ME_dPISTME_design_data = Column(Float, nullable=True)  # ME Piston Bore [m] — ***
    ME_sPISTME_design_data = Column(Float, nullable=True)  # ME Piston Stroke [m] — ***
    ME_PMCRME_design_data = Column(Float, nullable=True)  # ME Power at MCR [kW] — ***
    ME_PNCRME_design_data = Column(Float, nullable=True)  # ME Power at NCR [kW] — **
    ME_NMCRME_design_data = Column(Float, nullable=True)  # ME Rotational Speed at MCR [RPM] — ***
    ME_NNCRME_design_data = Column(Float, nullable=True)  # ME Rotational Speed at NCR [RPM] — **
    ME_DualFuelME_design_data = Column(TEXT, nullable=True)  # ME Dual Fuel Capability
    ME_VEGBPME_design_data = Column(TEXT, nullable=True)  # ME Variable Exhaust Gas Bypass Capability
    ME_LIWATME_design_data = Column(TEXT, nullable=True)  # ME Liner Wall Temperature Monitoring Capability
    ME_IARME_design_data = Column(TEXT, nullable=True)  # ME ignition Angle Reading Capability
    ME_MBTME_design_data = Column(TEXT, nullable=True)  # ME Main Bearing Temperature Monitoring Capability
    ME_CBTME_design_data = Column(TEXT, nullable=True)  # ME Crosshead Bearing Temperature Monitoring Capability
    ME_AVME_design_data = Column(TEXT, nullable=True)  # ME Axial Vibration Monitoring Capability
    ME_TVME_design_data = Column(TEXT, nullable=True)  # ME Torsional Vibration Monitoring Capability
    ME_TCCOSME_design_data = Column(TEXT, nullable=True)  # ME TC Cut-Out System Capability
    ME_nTCME_design_data = Column(Integer, nullable=True)  # ME Number of TCs — ***
    ME_MakerTCME_design_data = Column(TEXT, nullable=True)  # ME TC Maker
    ME_ModelTCME_design_data = Column(TEXT, nullable=True)  # ME TC Model
    ME_NmaxTCME_design_data = Column(Float, nullable=True)  # ME TC Maximum Rotational Speed [RPM]
    ME_TmaxTCME_design_data = Column(Float, nullable=True)  # ME TC Maximum Temperature [°C]
    ME_muTCME_design_data = Column(Float, nullable=True)  # ME TC Compressor Slip Factor
    ME_dTCcompME_design_data = Column(Float, nullable=True)  # ME TC Compressor Diameter [m]
    ME_TypeGovME_design_data = Column(TEXT, nullable=True)  # ME Governor Type
    ME_ModelGovME_design_data = Column(TEXT, nullable=True)  # ME Governor Model
    ME_TypeLBME_design_data = Column(TEXT, nullable=True)  # ME Lubricator Type
    ME_MakerLBME_design_data = Column(TEXT, nullable=True)  # ME Lubricator Maker
    ME_ModelLBME_design_data = Column(TEXT, nullable=True)  # ME Lubricator Model
    ME_CoolantJKTME_design_data = Column(TEXT, nullable=True)  # ME Jacket Coolant
    ME_CoolantFOVVME_design_data = Column(TEXT, nullable=True)  # ME FO Valve Coolant
    ME_CoolantLOCoolerME_design_data = Column(TEXT, nullable=True)  # ME LO Cooler Coolant
    ME_CoolantACME_design_data = Column(TEXT, nullable=True)  # ME AC Coolant
    ME_CoolantTCME_design_data = Column(TEXT, nullable=True)  # ME TC Coolant
    ME_nSPME_design_data = Column(Float, nullable=True)  # ME Number of Swash Plates
    ME_nACTRME_design_data = Column(Float, nullable=True)  # ME Number of Actuators
    ME_MakerDiagToolME_design_data = Column(TEXT, nullable=True)  # ME Performance Diagnostic Tool Maker
    ME_ModelDiagToolME_design_data = Column(TEXT, nullable=True)  # ME Performance Diagnostic Tool Model
    ME_TypeDiagToolME_design_data = Column(TEXT, nullable=True)  # ME Performance Diagnostic Tool Type
    ME_InstallationDiagToolME_design_data = Column(TEXT, nullable=True)  # ME Performance Diagnostic Tool Installation
    ME_etaeffME_design_data = Column(Float, nullable=True)  # ME Mechanical Efficienc (etaE=PB/Peff)
    ME_RegLBME_design_data = Column(TEXT, nullable=True)  # MAN Engines: Less than breakpoint RPM or power regulated?
    ME_SCOCbME_design_data = Column(Float, nullable=True)  # ME SCOC Basic Feed Rate [g/kWh]
    ME_SCOCminME_design_data = Column(Float, nullable=True)  # ME SCOC Minimum Feed Rate [g/kWh]
    ME_SCOCmaxME_design_data = Column(Float, nullable=True)  # ME SCOC Maximum Feed Rate [g/kWh]
    ME_BNLBME_design_data = Column(Integer, nullable=True)  # ME BN for Cylinder Oil used during sweep test [mgKOH/g]
    ME_ACCLBME_design_data = Column(Float, nullable=True)  # ME ACC factor established during sweep test [g/kWh%S]
    ME_Breakpoint_design_data = Column(Integer, nullable=True)  # Breakpoint Load [%]
    ME_WECS_design_data = Column(TEXT, nullable=True)  # Wartsila Engine Control System
    ME_HMI_design_data = Column(Integer, nullable=True)  # Human Machine Interface Setting [%]
    ME_EthanolME_design_data = Column(TEXT, nullable=True)  # ME Ethanol Consumption capability
    ME_MethanolME_design_data = Column(TEXT, nullable=True)  # ME Methanol Consumption capability
    ME_LPGPME_design_data = Column(TEXT, nullable=True)  # ME LPGP Consumption capability
    ME_LPGBME_design_data = Column(TEXT, nullable=True)  # ME LPGB Consumption capability
    ME_ModeMESim_design_data = Column(Float, nullable=True)  # ME Mode from Simulation
    ME_MCRMESim_design_data = Column(TEXT, nullable=True)  # ME MCR Percentage from Simulation [%]
    ME_NMESim_design_data = Column(TEXT, nullable=True)  # ME Rotational Speed from Simulation [RPM]
    ME_PMESim_design_data = Column(TEXT, nullable=True)  # ME Power from Simulation [kW]
    ME_SFOCisoMESim_design_data = Column(TEXT, nullable=True)  # ME SFOC ISO Corrected from Simulation [g/kWh]
    ME_TegEVoutMESim_design_data = Column(TEXT, nullable=True)  # ME Average Exhaust Gas Temperature after Exhaust Valve from Simulation [°C]
    ME_mdotegMESim_design_data = Column(TEXT, nullable=True)  # ME Exhaust Gas Flow from Simulation [kg/s]
    ME_mdotSteamProductionMESim_design_data = Column(TEXT, nullable=True)  # ME Exhaust Gas Boiler Steam Production from Simulation [kg/h]
    ME_HullNoMEST_design_data = Column(TEXT, nullable=True)  # Hull No of the Selected ME Shop Test Report
    ME_NoME_design_data = Column(Integer, nullable=True)  # ME Serial No of the Selected ME Shop Test Report — ***
    ME_PistConfME_design_data = Column(TEXT, nullable=True)  # ME Piston Configuration
    ME_PowerTypeMEST_design_data = Column(TEXT, nullable=True)  # Power Type in ME Shop Test
    ME_ModeMEST_design_data = Column(Float, nullable=True)  # ME Mode during Shop Test
    ME_etaeff_design_data = Column(Float, nullable=True)  # ME Mechanical Efficiency (etaE=PB/Peff)
    ME_LCVFOMEST_design_data = Column(Float, nullable=True)  # ME FO LCV during Shop Test [Mj/kg] — ***
    ME_rhoFOMEST_design_data = Column(Float, nullable=True)  # ME FO Density during Shop Test [kg/m3] — ***
    ME_MCRMEST_design_data = Column(TEXT, nullable=True)  # ME MCR Percentage during Shop Test [%] — ***
    ME_NMEST_design_data = Column(TEXT, nullable=True)  # ME Rotational Speed during Shop Test [RPM] — ***
    ME_PMEST_design_data = Column(TEXT, nullable=True)  # ME Power during Shop Test [kW] — ***
    ME_NTCMEST_design_data = Column(TEXT, nullable=True)  # ME Average TC Rotational Speed during Shop Test [RPM] — ***
    ME_FPIMEST_design_data = Column(TEXT, nullable=True)  # ME Average Fuel Pump Index during Shop Test — ***
    ME_TFOPPinMEST_design_data = Column(TEXT, nullable=True)  # ME FO Temperature at Fuel Pump Inlet during Shop Test [°C] — ***
    ME_FOCMEST_design_data = Column(TEXT, nullable=True)  # ME FO Consumption during Shop Test [kg/h] — ***
    ME_SFOCMEST_design_data = Column(TEXT, nullable=True)  # ME SFOC during Shop Test [g/kWh]
    ME_SFOCisoMEST_design_data = Column(TEXT, nullable=True)  # ME SFOC ISO Corrected during Shop Test [g/kWh]
    ME_TairTCinMEST_design_data = Column(TEXT, nullable=True)  # ME Average Air Temperature at TC Inlet during Shop Test [°C] — ***
    ME_pambairMEST_design_data = Column(TEXT, nullable=True)  # Ambient Air Pressure during ME Shop Test [mbar] — ***
    ME_TscavMEST_design_data = Column(TEXT, nullable=True)  # ME Average Scavenge Air Temperature during Shop Test [°C] — ***
    ME_pscavMEST_design_data = Column(TEXT, nullable=True)  # ME Average Scavenge Air Pressure during Shop Test [bar] — **
    ME_pindMEST_design_data = Column(TEXT, nullable=True)  # ME Average Mean Indicated Pressure during Shop Test [bar] — *
    ME_peffMEST_design_data = Column(TEXT, nullable=True)  # ME Average Mean Effective Pressure during Shop Test [bar] — ***
    ME_pmaxMEST_design_data = Column(TEXT, nullable=True)  # ME Average Maximum Combustion Pressure during Shop Test [bar] — *
    ME_pcompMEST_design_data = Column(TEXT, nullable=True)  # ME Average Compression Pressure during Shop Test [bar] — *
    ME_TegEVoutMEST_design_data = Column(TEXT, nullable=True)  # ME Average Exhaust Gas Temperature after Exhaust Valve during Shop Test [°C] — **
    ME_pegRMEST_design_data = Column(TEXT, nullable=True)  # ME Average Exhaust Gas Pressure at Receiver during Shop Test [bar] — *
    ME_TegTCinMEST_design_data = Column(TEXT, nullable=True)  # ME Average Exhaust Gas Temperature at TC Inlet during Shop Test [°C] — *
    ME_pegTCinMEST_design_data = Column(TEXT, nullable=True)  # ME Average Exhaust Gas Pressure at TC Inlet during Shop Test [bar] — *
    ME_TegTCoutMEST_design_data = Column(TEXT, nullable=True)  # ME Average Exhaust Gas Temperature at TC Outlet during Shop Test [°C] — *
    ME_pegTCoutMEST_design_data = Column(TEXT, nullable=True)  # ME Average Exhaust Gas Pressure at TC Outlet during Shop Test [mbar] — ***
    ME_TcwACinMEST_design_data = Column(TEXT, nullable=True)  # ME Average Cooling Water Temperature at AC Inlet during Shop Test [°C] — ***
    ME_TcwACoutMEST_design_data = Column(TEXT, nullable=True)  # ME Average Cooling Water Temperature at AC Outlet during Shop Test [°C] — *
    ME_TairACinMEST_design_data = Column(TEXT, nullable=True)  # ME Average Air Temperature at AC Inlet during Shop Test [°C] — *
    ME_TairACoutMEST_design_data = Column(TEXT, nullable=True)  # ME Average Air Temperature at AC Outlet during Shop Test [°C] — *
    ME_dpairACMEST_design_data = Column(TEXT, nullable=True)  # ME Average Air Pressure Drop across AC during Shop Test [mmWC] — *
    ME_dpairAFMEST_design_data = Column(TEXT, nullable=True)  # ME Average Air Pressure Drop across AF during Shop Test [mmWC] — *
    ME_MCRNOxMEST_design_data = Column(TEXT, nullable=True)  # ME MCR Percentage during NOx Emissions Test [%]
    ME_NOxisoMEST_design_data = Column(TEXT, nullable=True)  # ME NOx Emissions during NOx Emissions Test (ISO) [g/kWh]
    ME_AuxBlowMEST_design_data = Column(TEXT, nullable=True)  # ME Auxiliary Blower during Shop Test
    ME_nMEST_design_data = Column(Integer, nullable=True)  # Number of ME Shop Tests
    ME_FuelModeMEST_design_data = Column(TEXT, nullable=True)  # ME Fuel Mode
    ME_LCVGOMEST_design_data = Column(Float, nullable=True)  # ME Gas LCV during Shop Test [Mj/kg]
    ME_rhoGOMEST_design_data = Column(Float, nullable=True)  # ME Gas Density during Shop Test [kg/m3]
    ME_TGOinMEST_design_data = Column(TEXT, nullable=True)  # ME Gas Temperature at Engine Inlet during Shop Test [°C]
    ME_pGOinMEST_design_data = Column(TEXT, nullable=True)  # ME Gas Pressure at Engine Inlet during Shop Test [bar]
    ME_GOCMEST_design_data = Column(TEXT, nullable=True)  # ME Gas Consumption during Shop Test [kg/h]
    ME_SGOCMEST_design_data = Column(TEXT, nullable=True)  # ME SGOC during Shop Test [g/kWh]
    ME_SGOCisoMEST_design_data = Column(TEXT, nullable=True)  # ME SGOC ISO Corrected during Shop Test [g/kWh]
    AE_nAE_design_data = Column(Integer, nullable=True)  # Number of AEs — *
    AE_MakerAE_design_data = Column(TEXT, nullable=True)  # AE Maker
    AE_BuilderAE_design_data = Column(TEXT, nullable=True)  # AE Licensee/Builder
    AE_PistConfAE_design_data = Column(TEXT, nullable=True)  # AE Piston Configuration
    AE_ModelAE_design_data = Column(TEXT, nullable=True)  # AE Model
    AE_SerNoAE_design_data = Column(TEXT, nullable=True)  # AE Serial No
    AE_ncAE_design_data = Column(Integer, nullable=True)  # AE Number of Cylinders
    AE_dPISTAE_design_data = Column(Float, nullable=True)  # AE Piston Bore [m]
    AE_sPISTAE_design_data = Column(Float, nullable=True)  # AE Piston Stroke [m]
    AE_PengnomAE_design_data = Column(Float, nullable=True)  # AE Nominal Engine Power [kW] — **
    AE_PgennomAAE_design_data = Column(Float, nullable=True)  # AE Nominal Generator Power [kVA] — **
    AE_NnomAE_design_data = Column(Float, nullable=True)  # AE Nominal Rotational Speed [RPM]
    AE_PFnomAE_design_data = Column(Float, nullable=True)  # AE Power Factor — **
    AE_DualFuelAE_design_data = Column(TEXT, nullable=True)  # AE Dual Fuel Capability — *
    AE_ECNTRAE_design_data = Column(TEXT, nullable=True)  # AE Energy Counter Capability — *
    AE_nTCAE_design_data = Column(Integer, nullable=True)  # AE Number of TCs
    AE_MakerTCAE_design_data = Column(TEXT, nullable=True)  # AE TC Maker
    AE_ModelTCAE_design_data = Column(TEXT, nullable=True)  # AE TC Model
    AE_nTCinletAE_design_data = Column(Float, nullable=True)  # AE TC Number of Inlets
    AE_NmaxTCAE_design_data = Column(Float, nullable=True)  # AE TC Maximum Rotational Speed [RPM]
    AE_TmaxTCAE_design_data = Column(Float, nullable=True)  # AE TC Maximum Temperature [°C]
    AE_muTCAE_design_data = Column(Float, nullable=True)  # AE TC Compressor Slip Factor
    AE_dTCcompAE_design_data = Column(Float, nullable=True)  # AE TC Compressor Diameter [m]
    AE_CoolantJKTAE_design_data = Column(TEXT, nullable=True)  # AE Jacket Coolant
    AE_CoolantFOVVAE_design_data = Column(TEXT, nullable=True)  # AE FO Valve Coolant
    AE_CoolantLOCoolerAE_design_data = Column(TEXT, nullable=True)  # AE LO Cooler Coolant
    AE_CoolantACAE_design_data = Column(TEXT, nullable=True)  # AE AC Coolant
    AE_CoolantTCAE_design_data = Column(TEXT, nullable=True)  # AE TC Coolant
    AE_MakerDiagToolAE_design_data = Column(TEXT, nullable=True)  # AE Performance Diagnostic Tool Maker
    AE_ModelDiagToolAE_design_data = Column(TEXT, nullable=True)  # AE Performance Diagnostic Tool Model
    AE_TypeDiagToolAE_design_data = Column(TEXT, nullable=True)  # AE Performance Diagnostic Tool Type
    AE_InstallationDiagToolAE_design_data = Column(TEXT, nullable=True)  # AE Performance Diagnostic Tool Installation
    AE_SFCAE_design_data = Column(Float, nullable=True)  # Avg AE SFOC at 50% MCR (ISO Corrected) [g/kW-hr]
    AE_SFCPilotAE_design_data = Column(Float, nullable=True)  # Avg AE  Pilot fuel SFOC at 50% on Gas Mode (ISO Corrected) [g/kW-hr]
    AE_SGCAE_design_data = Column(Float, nullable=True)  # Avg AE SGOC at 50% MCR (ISO Corrected) [g/kW-hr]
    AE_AECnt_design_data = Column(TEXT, nullable=True)  # Is AE Running Hour Counter available?
    AE_AEEC_design_data = Column(TEXT, nullable=True)  # AE Ethanol Consumption Capability
    AE_LPGBAE_design_data = Column(TEXT, nullable=True)  # AE LPGB Consumption Capability
    AE_LPGPAE_design_data = Column(TEXT, nullable=True)  # AE LPGP Consumption Capability
    AE_AEMC_design_data = Column(TEXT, nullable=True)  # AE Methanol Consumption Capability
    AE_AE_Consumer_Class_design_data = Column(TEXT, nullable=True)  # Auxiliary Engine Consumer Class
    AE_HullNoAEST_design_data = Column(TEXT, nullable=True)  # Hull No of the Selected AE Shop Test Report — *
    AE_LCVFOAEST_design_data = Column(Float, nullable=True)  # AE FO LCV during Shop Test [Mj/kg] — *
    AE_rhoFOAEST_design_data = Column(Float, nullable=True)  # AE FO Density during Shop Test [kg/m3] — *
    AE_MCRAEST_design_data = Column(TEXT, nullable=True)  # AE MCR Percentage during Shop Test [%] — *
    AE_NAEST_design_data = Column(TEXT, nullable=True)  # AE Rotational Speed during Shop Test [RPM] — *
    AE_PengAEST_design_data = Column(TEXT, nullable=True)  # AE Engine Power during Shop Test [kW]
    AE_PgenAEST_design_data = Column(TEXT, nullable=True)  # AE Generator Power during Shop Test [kW]
    AE_NTCAEST_design_data = Column(TEXT, nullable=True)  # AE Average TC Rotational Speed during Shop Test [RPM]
    AE_FPIAEST_design_data = Column(TEXT, nullable=True)  # AE Average Fuel Pump Index during Shop Test [mm or % or -]
    AE_TFOPPinAEST_design_data = Column(TEXT, nullable=True)  # AE FO Temperature at Fuel Pump Inlet during Shop Test [°C]
    AE_FOCAEST_design_data = Column(TEXT, nullable=True)  # AE FO Consumption during Shop Test [kg/h] — *
    AE_SFOCAEST_design_data = Column(TEXT, nullable=True)  # AE SFOC during Shop Test [g/kWh]
    AE_SFOCisoAEST_design_data = Column(TEXT, nullable=True)  # AE SFOC ISO Corrected during Shop Test [g/kWh]
    AE_TairTCinAEST_design_data = Column(TEXT, nullable=True)  # AE Average Air Temperature at TC Inlet during Shop Test [°C] — *
    AE_pairTCinAEST_design_data = Column(TEXT, nullable=True)  # AE Average Air Pressure at TC Inlet during Shop Test [mbar]
    AE_pmaxAEST_design_data = Column(TEXT, nullable=True)  # AE Average Maximum Combustion Pressure during Shop Test [bar]
    AE_pcompAEST_design_data = Column(TEXT, nullable=True)  # AE Average Compression Pressure during Shop Test [bar]
    AE_TegEVoutAEST_design_data = Column(TEXT, nullable=True)  # AE Average Exhaust Gas Temperature after Exhaust Valve during Shop Test [°C] — *
    AE_TegTCinAEST_design_data = Column(TEXT, nullable=True)  # AE Average Exhaust Gas Temperature at TC Inlet during Shop Test [°C]
    AE_TegTCoutAEST_design_data = Column(TEXT, nullable=True)  # AE Average Exhaust Gas Temperature at TC Outlet during Shop Test [°C]
    AE_TcwACinAEST_design_data = Column(TEXT, nullable=True)  # AE Average Cooling Water Temperature at AC Inlet during Shop Test [°C] — *
    AE_TcwACoutAEST_design_data = Column(TEXT, nullable=True)  # AE Average Cooling Water Temperature at AC Outlet during Shop Test [°C]
    AE_TairACinAEST_design_data = Column(TEXT, nullable=True)  # AE TC AC Average Air Inlet Temperature during Shop Test [°C]
    AE_TairACoutAEST_design_data = Column(TEXT, nullable=True)  # AE TC AC Average Air Outlet Temperature during Shop Test [°C]
    AE_pairACoutAEST_design_data = Column(TEXT, nullable=True)  # AE TC AC Average Air Outlet Pressure during Shop Test [bar]
    AE_dpairACAEST_design_data = Column(TEXT, nullable=True)  # AE Average Air Pressure Drop across TC AC during Shop Test [mmWC]
    AE_dpairAFAEST_design_data = Column(TEXT, nullable=True)  # AE Average Air Pressure Drop across TC AF during Shop Test [mmWC]
    AE_MCRNOxAEST_design_data = Column(TEXT, nullable=True)  # AE MCR Percentage during NOx Emissions Test [%]
    AE_NOxisoAEST_design_data = Column(TEXT, nullable=True)  # AE NOx Emissions during NOx Emissions Test (ISO) [g/kWh]
    AE_EngNoAEST_design_data = Column(TEXT, nullable=True)  # Engine No of the Selected AE Shop Test Report
    AE_LoadTypeAEST_design_data = Column(TEXT, nullable=True)  # Percentage Load Type in AE Shop Test — *
    AE_SerNoAEST_design_data = Column(TEXT, nullable=True)  # AE Serial No of the Selected Shop Test Report — *
    AE_NoAE_design_data = Column(Integer, nullable=True)  # AE No — **
    AE_FuelModeAEST_design_data = Column(TEXT, nullable=True)  # AE Fuel Mode — **
    AE_pambairAEST_design_data = Column(TEXT, nullable=True)  # Ambient Air Pressure (Abs.) during AE Shop Test [mbar] — *
    AE_pscavAEST_design_data = Column(TEXT, nullable=True)  # AE Average Scavenge Air Pressure during Shop Test [bar] — *
    AE_etagenAEST_design_data = Column(TEXT, nullable=True)  # AE Generator Efficiency (etagen=Pgen/Peng at PF=1)
    AE_TscavAEST_design_data = Column(TEXT, nullable=True)  # AE Average Scavenge Air Temperature during Shop Test [°C]
    AE_nAEST_design_data = Column(Integer, nullable=True)  # Number of AE Shop Tests — **
    AE_LCVGOAEST_design_data = Column(Float, nullable=True)  # AE Gas LCV during Shop Test [Mj/kg]
    AE_rhoGOAEST_design_data = Column(Float, nullable=True)  # AE Gas Density during Shop Test [kg/m3]
    AE_TGOinAEST_design_data = Column(TEXT, nullable=True)  # AE Gas Temperature at Engine Inlet during Shop Test [°C]
    AE_pGOinAEST_design_data = Column(TEXT, nullable=True)  # AE Gas Pressure at Engine Inlet during Shop Test [bar]
    AE_GOCAEST_design_data = Column(TEXT, nullable=True)  # AE Gas Consumption during Shop Test [kg/h]
    AE_SGOCAEST_design_data = Column(TEXT, nullable=True)  # AE SGOC during Shop Test [g/kWh]
    AE_SGOCisoAEST_design_data = Column(TEXT, nullable=True)  # AE SGOC ISO Corrected during Shop Test [g/kWh]
    Boiler_nBL_design_data = Column(Integer, nullable=True)  # Number of Boilers
    Boiler_MakerBL_design_data = Column(TEXT, nullable=True)  # Boiler Maker
    Boiler_ModelBL_design_data = Column(TEXT, nullable=True)  # Boiler Model
    Boiler_DualFuelBL_design_data = Column(TEXT, nullable=True)  # Boiler Dual Fuel Capability
    Boiler_SteamCapacityBL_design_data = Column(Float, nullable=True)  # Boiler Steam Capacity [kg/hr]
    Boiler_FluidBL_design_data = Column(TEXT, nullable=True)  # Boiler fluid
    Boiler_BLCnt_design_data = Column(TEXT, nullable=True)  # Is Aux Boiler Running Hour Counter available?
    Boiler_EthanolBL_design_data = Column(TEXT, nullable=True)  # Aux Boiler Ethanol Consumption capability
    Boiler_LPGBBL_design_data = Column(TEXT, nullable=True)  # Aux Boiler LPGB Consumption capability
    Boiler_LPGPBL_design_data = Column(TEXT, nullable=True)  # Aux Boiler LPGP Consumption capability
    Boiler_MethanolBL_design_data = Column(TEXT, nullable=True)  # Aux Boiler Methanol Consumption capability
    CompositeBoiler_ComBL_design_data = Column(TEXT, nullable=True)  # Composite Boiler Installed?
    CompositeBoiler_nComBL_design_data = Column(Integer, nullable=True)  # No of Composite Boilers
    CompositeBoiler_ModelComBL_design_data = Column(TEXT, nullable=True)  # Composite Boiler Model
    CompositeBoiler_MakerComBL_design_data = Column(TEXT, nullable=True)  # Composite Boiler Maker
    CompositeBoiler_ComBLCnt_design_data = Column(TEXT, nullable=True)  # Is Running hour counter available?
    CompositeBoiler_SteamCapacityComBL_design_data = Column(Float, nullable=True)  # Composite Boiler Steam Capacity [kg/hr]
    CompositeBoiler_LPGBComBL_design_data = Column(TEXT, nullable=True)  # ComBL LPGB Consumption capability
    CompositeBoiler_MethanolComBL_design_data = Column(TEXT, nullable=True)  # ComBL Methanol Consumption capability
    CompositeBoiler_EthanolComBL_design_data = Column(TEXT, nullable=True)  # ComBL Ethanol Consumption capability
    CompositeBoiler_LPGPComBL_design_data = Column(TEXT, nullable=True)  # ComBL LPGP Consumption capability
    HPP_HPPinstalled_design_data = Column(TEXT, nullable=True)  # Is HPP installed? (Electric driven)
    HPP_nHPP_design_data = Column(Integer, nullable=True)  # Number of HPPs (Electric driven)
    HPP_HPPCnt_design_data = Column(TEXT, nullable=True)  # Is HPP Running Counters available?
    HPP_TypeHPP_design_data = Column(TEXT, nullable=True)  # Type of HPP (Electric driven)
    HPP_MakerHPP_design_data = Column(TEXT, nullable=True)  # HPP Maker
    HPP_ModelHPP_design_data = Column(TEXT, nullable=True)  # HPP Model
    HPP_CapacityHPP_design_data = Column(Float, nullable=True)  # HPP Capacity [kW]
    DPP_DPPinstalled_design_data = Column(TEXT, nullable=True)  # Is DPP installed?
    DPP_nDPP_design_data = Column(Integer, nullable=True)  # Number of DPPs
    DPP_DPPCnt_design_data = Column(TEXT, nullable=True)  # Is DPP Running Counters available?
    DPP_TypeDPP_design_data = Column(TEXT, nullable=True)  # Type of DPP
    DPP_MakerDPP_design_data = Column(TEXT, nullable=True)  # DPP Maker
    DPP_ModelDPP_design_data = Column(TEXT, nullable=True)  # DPP Model
    DPP_CapacityDPP_design_data = Column(Float, nullable=True)  # DPP Capacity [kW]
    EEDI_ReeferCapability_design_data = Column(TEXT, nullable=True)  # Reefer Carrying Capability
    EEDI_ECNTRReefer_design_data = Column(TEXT, nullable=True)  # Reefer Energy Counter Capability
    EEDI_ECNTRCargoPump_design_data = Column(TEXT, nullable=True)  # Energy Counter Capability for Cargo Discharging
    EEDI_TypeCargoPump_design_data = Column(TEXT, nullable=True)  # Cargo Pump Type
    EEDI_CargoCoolingCapability_design_data = Column(TEXT, nullable=True)  # Cargo Cooling Capability
    EEDI_ECNTRCargoCool_design_data = Column(TEXT, nullable=True)  # Energy Counter Capability for Cargo Cooling
    EEDI_EEDITF_design_data = Column(TEXT, nullable=True)  # EEDI Technical File
    EEDI_EEDIattTF_design_data = Column(Float, nullable=True)  # Attained EEDI from Technical File
    EEDI_IceClassNotation_design_data = Column(TEXT, nullable=True)  # Ice Class Notation
    EEDI_CSRClassNotation_design_data = Column(TEXT, nullable=True)  # Common Structural Rules Class Notation
    EEDI_RPClassNotation_design_data = Column(TEXT, nullable=True)  # Redundancy Propulsion Class Notation
    EEDI_VSEClassNotation_design_data = Column(TEXT, nullable=True)  # Voluntary Structural Enhancement Class Notation
    EEDI_DWTenhanced_design_data = Column(Float, nullable=True)  # Enhanced DWT at scantling draft [MT]
    EEXI_Fi_design_data = Column(Float, nullable=True)  # Capacity Correction Factor For ICE Class Vessels
    EEXI_Fm_design_data = Column(Float, nullable=True)  # Factor For ICE Class Ships Having 1A Super1A
    EEXI_Fc_design_data = Column(Float, nullable=True)  # Cubic Capacity Correction Factor
    EEXI_Fivse_design_data = Column(Float, nullable=True)  # Correction Factor For Ship-Specific Voluntary Enhancement
    EEXI_ES_design_data = Column(TEXT, nullable=True)  # EPL/SHAPOLI
    EEXI_EPLOver_design_data = Column(TEXT, nullable=True)  # EPL Over Rideable
    EEXI_ReqEEXI_design_data = Column(Float, nullable=True)  # Required EEXI Value [g/Tonnes-Miles]
    EEXI_AttaEEXI_design_data = Column(Float, nullable=True)  # Attained EEXI Value [g/Tonnes-Miles]
    Flowmeter_nFM_design_data = Column(Float, nullable=True)  # Total Number of FMs
    Flowmeter_FluidFM_design_data = Column(TEXT, nullable=True)  # FM Fluid
    Flowmeter_LocationFM_design_data = Column(TEXT, nullable=True)  # FM Location
    Flowmeter_TypeFM_design_data = Column(TEXT, nullable=True)  # FM Type
    Flowmeter_MakerFM_design_data = Column(TEXT, nullable=True)  # FM Maker
    Flowmeter_ModelFM_design_data = Column(TEXT, nullable=True)  # FM Model
    Flowmeter_FaccuracyFM_design_data = Column(Float, nullable=True)  # FM Accuracy [%]
    Flowmeter_InterfaceFM_design_data = Column(TEXT, nullable=True)  # FM Interface Type
    Flowmeter_EquipmentFM_new_design_data = Column(TEXT, nullable=True)  # FM for Equipment (new)
    SpeedLog_MakerSL_design_data = Column(TEXT, nullable=True)  # SL Maker
    SpeedLog_ModelSL_design_data = Column(TEXT, nullable=True)  # SL Model
    SpeedLog_UaccuracySL_design_data = Column(Float, nullable=True)  # SL Accuracy [%]
    ShaftPowermeter_SPM_design_data = Column(TEXT, nullable=True)  # SPM Installed
    ShaftPowermeter_nSPM_design_data = Column(Float, nullable=True)  # Number of SPMs
    ShaftPowermeter_ECNTRSPM_design_data = Column(TEXT, nullable=True)  # SPM Energy Counter Capability
    ShaftPowermeter_LocationSPM_design_data = Column(TEXT, nullable=True)  # SPM Location
    ShaftPowermeter_MakerSPM_design_data = Column(TEXT, nullable=True)  # SPM Maker
    ShaftPowermeter_ModelSPM_design_data = Column(TEXT, nullable=True)  # SPM Model
    ShaftPowermeter_QaccuracySPM_design_data = Column(Float, nullable=True)  # SPM Torquemeter Accuracy [%]
    ShaftPowermeter_NaccuracySPM_design_data = Column(Float, nullable=True)  # SPM Rotational Speed Sensor Accuracy [%]
    ShaftPowermeter_InterfaceSPM_design_data = Column(TEXT, nullable=True)  # SPM Interface Type
    SideThruster_SThruster_design_data = Column(TEXT, nullable=True)  # Side Thrusters Installed
    SideThruster_nSThruster_design_data = Column(Float, nullable=True)  # Number of Side Thrusters
    SideThruster_LocationSThruster_design_data = Column(TEXT, nullable=True)  # Side Thruster Location
    SideThruster_dSThruster_design_data = Column(Float, nullable=True)  # Side Thruster Diameter [m]
    SideThruster_pitchSThruster_design_data = Column(Float, nullable=True)  # Side Thruster Pitch [m]
    SideThruster_dtunSThruster_design_data = Column(Float, nullable=True)  # Side Thruster Tunnel Diameter [m]
    SideThruster_VnomSThruster_design_data = Column(Float, nullable=True)  # Side Thruster Nominal Volt [V]
    SideThruster_AnomSThruster_design_data = Column(Float, nullable=True)  # Side Thruster Nominal Ampere [A]
    SideThruster_PnomSThruster_design_data = Column(Float, nullable=True)  # Side Thruster Nominal Power [kW]
    SideThruster_NnomSThruster_design_data = Column(Float, nullable=True)  # Side Thruster Nominal Rotational Speed [RPM]
    GCU_GCU_design_data = Column(TEXT, nullable=True)  # GCU Installed
    GCU_nGCU_design_data = Column(Float, nullable=True)  # Number of GCUs
    GCU_MakerGCU_design_data = Column(TEXT, nullable=True)  # GCU Maker
    GCU_ModelGCU_design_data = Column(TEXT, nullable=True)  # GCU Model
    GCU_CapacityGCU_design_data = Column(Float, nullable=True)  # GCU Capacity [kg/hr]
    GCU_EthanolGCU_design_data = Column(TEXT, nullable=True)  # GCU Ethanol Consumption capability
    GCU_MethanolGCU_design_data = Column(TEXT, nullable=True)  # GCU Methanol Consumption capability
    GCU_LPGPGCU_design_data = Column(TEXT, nullable=True)  # GCU LPGP Consumption capability
    GCU_LPGBGCU_design_data = Column(TEXT, nullable=True)  # GCU LPGB Consumption capability
    ShaftGenerator_SG_design_data = Column(TEXT, nullable=True)  # SG Installed — **
    ShaftGenerator_nSG_design_data = Column(Integer, nullable=True)  # Number of SGs
    ShaftGenerator_ECNTRSG_design_data = Column(TEXT, nullable=True)  # SG Energy Counter Capability
    ShaftGenerator_MakerSG_design_data = Column(TEXT, nullable=True)  # SG Maker
    ShaftGenerator_ModelSG_design_data = Column(TEXT, nullable=True)  # SG Model
    ShaftGenerator_PnomSG_design_data = Column(Float, nullable=True)  # SG Nominal Power [kW]
    ShaftGenerator_NnomSG_design_data = Column(Float, nullable=True)  # SG Nominal Rotational Speed [RPM]
    ShaftGenerator_etaSG_design_data = Column(Float, nullable=True)  # SG Electrical Efficiency
    ReductionGear_RG_design_data = Column(TEXT, nullable=True)  # RG Installed — **
    ReductionGear_nRG_design_data = Column(Float, nullable=True)  # Number of RGs
    ReductionGear_MakerRG_design_data = Column(TEXT, nullable=True)  # RG Maker
    ReductionGear_ModelRG_design_data = Column(TEXT, nullable=True)  # GR Model
    ReductionGear_RatioRG_design_data = Column(Float, nullable=True)  # RG Transmition Ratio
    ReductionGear_etaRG_design_data = Column(Float, nullable=True)  # RG Efficiency
    SteamTurbine_STurbine_design_data = Column(TEXT, nullable=True)  # Steam Turbine Installed
    SteamTurbine_nSTurbine_design_data = Column(Float, nullable=True)  # Number of Steam Turbines
    SteamTurbine_MakerSTurbine_design_data = Column(TEXT, nullable=True)  # Steam Turbine Maker
    SteamTurbine_ModelSTurbine_design_data = Column(TEXT, nullable=True)  # Steam Turbine Model
    SteamTurbine_PnomSTurbine_design_data = Column(Float, nullable=True)  # Steam Turbine Nominal Power [kW]
    SteamTurbine_NnomSTurbine_design_data = Column(Float, nullable=True)  # Steam Turbine Rotational Speed [RPM]
    SteamTurbine_DualFuelSTurbine_design_data = Column(TEXT, nullable=True)  # Steam Turbine Dual Fuel Capability
    GasTurbine_GTurbine_design_data = Column(TEXT, nullable=True)  # Gas Turbine Installed
    GasTurbine_nGTurbine_design_data = Column(Float, nullable=True)  # Number of Gas Turbines
    GasTurbine_MakerGTurbine_design_data = Column(TEXT, nullable=True)  # Gas Turbine Maker
    GasTurbine_ModelGTurbine_design_data = Column(TEXT, nullable=True)  # Gas Turbine Model
    GasTurbine_PnomGTurbine_design_data = Column(Float, nullable=True)  # Gas Turbine Nominal Power [kW]
    GasTurbine_NnomGTurbine_design_data = Column(Float, nullable=True)  # Gas Turbine Nominal Rotational Speed [RPM]
    GasTurbine_DualFuelGTurbine_design_data = Column(TEXT, nullable=True)  # Gas Turbine Dual Fuel Capability
    PropulsionMotor_PMotor_design_data = Column(TEXT, nullable=True)  # Propulsion Motor Installed — **
    PropulsionMotor_nPMotor_design_data = Column(Integer, nullable=True)  # Number of Propulsion Motors
    PropulsionMotor_MakerPMotor_design_data = Column(TEXT, nullable=True)  # Propulsion Motor Maker
    PropulsionMotor_ModelPMotor_design_data = Column(TEXT, nullable=True)  # Propulsion Motor Model
    PropulsionMotor_TypePMotor_design_data = Column(TEXT, nullable=True)  # Propulsion Motor Type
    PropulsionMotor_PnomPMotor_design_data = Column(Float, nullable=True)  # Propulsion Motor Nominal Power [kW]
    PropulsionMotor_NnomPMotor_design_data = Column(Float, nullable=True)  # Propulsion Motor Nominal Rotational Speed [RPM]
    IGG_IGG_design_data = Column(TEXT, nullable=True)  # IGG Installed
    IGG_nIGG_design_data = Column(Float, nullable=True)  # Number of IGGs
    IGG_MakerIGG_design_data = Column(TEXT, nullable=True)  # IGG Maker
    IGG_ModelIGG_design_data = Column(TEXT, nullable=True)  # IGG Model
    IGG_CpacityIGG_design_data = Column(Float, nullable=True)  # IGG Capacity [kg/hr]
    IGG_LPGPIGG_design_data = Column(TEXT, nullable=True)  # IGG LPGP Consumption capability
    IGG_LPGBIGG_design_data = Column(TEXT, nullable=True)  # IGG LPGB Consumption capability
    IGG_MethanolIGG_design_data = Column(TEXT, nullable=True)  # IGG Methanol Consumption capability
    IGG_EthanolIGG_design_data = Column(TEXT, nullable=True)  # IGG Ethanol Consumption capability
    INC_INC_design_data = Column(TEXT, nullable=True)  # Incinerator installed
    INC_nINC_design_data = Column(Float, nullable=True)  # Number of Incinerators
    INC_MakerINC_design_data = Column(TEXT, nullable=True)  # Incinerator Maker
    INC_ModelINC_design_data = Column(TEXT, nullable=True)  # Incinerator Model
    CharterParty_TmCP_design_data = Column(TEXT, nullable=True)  # CP Mean Draught [m]
    CharterParty_FwiCP_design_data = Column(Float, nullable=True)  # CP Wind [Bft]
    CharterParty_SSNCP_design_data = Column(Float, nullable=True)  # CP Sea State [DSS]
    CharterParty_UCP_design_data = Column(TEXT, nullable=True)  # CP Speed [kn]
    CharterParty_FOCMECP_design_data = Column(TEXT, nullable=True)  # CP FOC [MT/day]
    CharterParty_LCVFOMECP_design_data = Column(Float, nullable=True)  # CP LCV [Mj/kg]
    EG_EG_design_data = Column(TEXT, nullable=True)  # Emergency Generator Installed
    EG_nEG_design_data = Column(Integer, nullable=True)  # Number of Emergency Generators
    CargoTank_nCT_design_data = Column(Integer, nullable=True)  # No of Cargo Tanks
    CargoTank_nameCT_design_data = Column(TEXT, nullable=True)  # Name of Cargo Tank
    CargoTank_maxcapCT_design_data = Column(Float, nullable=True)  # Maximum Volume of cargo tanks [m3]
    CargoTank_isDeckTank_design_data = Column(TEXT, nullable=True)  # Is the tank a deck tank
    Compressor_nComp_design_data = Column(Integer, nullable=True)  # No of normal compressors
    Compressor_nrefComp_design_data = Column(Integer, nullable=True)  # No of refrigerant compressors
    FWG_FWGinstalled_design_data = Column(TEXT, nullable=True)  # FWG Installed?
    FWG_nFWG_design_data = Column(Integer, nullable=True)  # Number of FWGs
    FWG_TypeFWG_design_data = Column(TEXT, nullable=True)  # Type of Heat Exchanger used
    FWG_CapacityFWG_design_data = Column(Float, nullable=True)  # FWG Capacity [MT/Day]
    FWG_FWGCnt_design_data = Column(TEXT, nullable=True)  # Is FWG Running Counters available?
    FireFighting_nFIFIPump_design_data = Column(Integer, nullable=True)  # No of firefighting pump


# ============================================================
# ISO 19030 TABLES
# ============================================================

class VesselISOConfig(Base):
    """
    Stores per-vessel ISO 19030 configuration:
    vessel particulars for calculations, filter thresholds,
    environmental coefficients, KPI thresholds, SFOC curve.
    """
    __tablename__ = 'vessel_iso_config'

    vessel_imo       = Column(String(20), ForeignKey('vessels.imo_number', ondelete='CASCADE'), primary_key=True)

    # Vessel particulars (used in calculations)
    lpp_m            = Column(Float)          # Length between perpendiculars (m)
    breadth_m        = Column(Float)          # Moulded breadth B (m)
    block_coeff_cb   = Column(Float)          # Block coefficient Cb
    transverse_area_m2 = Column(Float)        # Transverse projected area A_T (m²)
    propeller_pitch_m  = Column(Float)        # Propeller design pitch (m)
    propulsive_eff_eta_d  = Column(Float, default=0.70)   # Propulsive efficiency η_D
    shaft_eff_eta_shaft   = Column(Float, default=0.98)   # Shaft efficiency η_shaft
    rho_ref_kgm3     = Column(Float, default=1025.0)      # Reference seawater density (kg/m³)

    # SFOC curve — JSON array of {load_pct, sfoc_gkwh, lcv_kjkg}
    sfoc_curve       = Column(JSONB)          # e.g. [{load_pct:25,sfoc:182,lcv:42700}, ...]

    # Filter thresholds (ISO 19030 defaults, can be overridden)
    wind_filter_ms          = Column(Float, default=5.5)
    wave_hs_max_m           = Column(Float, default=2.0)
    depth_draft_ratio_min   = Column(Float, default=6.0)
    rudder_max_deg          = Column(Float, default=5.0)
    rot_max_degmin          = Column(Float, default=10.0)
    loading_window_pct      = Column(Float, default=5.0)

    # Environmental coefficients
    c_aa             = Column(Float, default=0.80)    # Wind drag coefficient
    c_aw             = Column(Float, default=0.55)    # Wave form coefficient

    # Condition split
    condition_split_draft_m = Column(Float, default=8.5)   # mean draft ≤ this → Ballast
    active_baseline         = Column(String(2), default='B2')  # 'B1' or 'B2'

    # Reference displacements
    ref_displacement_laden_t   = Column(Float)   # Δ_refL (tonnes)
    ref_displacement_ballast_t = Column(Float)   # Δ_refB (tonnes)

    # KPI thresholds
    maintenance_trigger_pct = Column(Float, default=8.0)    # speed loss % → trigger YES
    amber_slope_pct30d      = Column(Float, default=0.5)    # amber alert slope %/30d
    red_slope_pct30d        = Column(Float, default=1.0)    # red alert slope %/30d
    rolling_window_records  = Column(Integer, default=7)    # rolling window for trigger

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class VesselBaselineCurve(Base):
    """
    Stores the 4 polynomial speed-power baseline curves per vessel:
    B1 Sea-Trial Laden, B1 Sea-Trial Ballast,
    B2 Post-DD Laden, B2 Post-DD Ballast.

    V_exp (kn) = a3*P^3 + a2*P^2 + a1*P + a0
    where P is in kW and coefficients use scale factors:
        a3 × 1e-12, a2 × 1e-8, a1 × 1e-3 (as in the ISO Excel)
    """
    __tablename__ = 'vessel_baseline_curves'

    id           = Column(Integer, primary_key=True)
    vessel_imo   = Column(String(20), ForeignKey('vessels.imo_number', ondelete='CASCADE'), index=True)
    generation   = Column(String(2), nullable=False)    # 'B1' or 'B2'
    condition    = Column(String(10), nullable=False)   # 'Laden' or 'Ballast'

    # Polynomial coefficients (stored at face value, scale factors applied in calculator)
    # V_exp = (a3*1e-12)*P^3 + (a2*1e-8)*P^2 + (a1*1e-3)*P + a0
    a3           = Column(Float, default=0.0)   # coefficient ×1e-12
    a2           = Column(Float, default=0.0)   # coefficient ×1e-8
    a1           = Column(Float, nullable=False)  # coefficient ×1e-3
    a0           = Column(Float, nullable=False)  # offset (kn)

    effective_from = Column(Date, nullable=True)   # date this baseline was established
    notes          = Column(TEXT, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        __import__('sqlalchemy').UniqueConstraint('vessel_imo', 'generation', 'condition', name='uq_baseline_curve'),
    )


class VesselMaintenanceEvent(Base):
    """
    Maintenance events: dry-docks, hull cleans, prop polishes.
    Used by KPI engine to define DD intervals and measure maintenance effect.
    """
    __tablename__ = 'vessel_maintenance_events'

    id          = Column(Integer, primary_key=True)
    vessel_imo  = Column(String(20), ForeignKey('vessels.imo_number', ondelete='CASCADE'), index=True)
    event_type  = Column(String(50), nullable=False)   # 'Dry-dock', 'Hull clean', 'Prop polish'
    event_date  = Column(Date, nullable=False)
    notes       = Column(TEXT, nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow)


class ISO19030Result(Base):
    """
    Stores per-record ISO 19030 calculation results.
    One row per analysis_data row that was processed.
    """
    __tablename__ = 'iso19030_results'

    id              = Column(Integer, primary_key=True)
    analysis_id     = Column(Integer, ForeignKey('analysis_data.id', ondelete='CASCADE'), unique=True, index=True)
    vessel_imo      = Column(String(20), ForeignKey('vessels.imo_number', ondelete='CASCADE'), index=True)
    record_date     = Column(Date, index=True)
    condition       = Column(String(10))        # 'Laden' or 'Ballast'

    # Stage 2 output
    stw_corr        = Column(Float)             # corrected STW (kn)

    # Stage 3 output
    filter_pass     = Column(Boolean)           # True = PASS, False = EXCL
    filter_reason   = Column(String(100))       # which filter failed (if any)

    # Stage 4 output
    delta_actual    = Column(Float)             # actual displacement (t)
    rho_sw          = Column(Float)             # seawater density (kg/m³)
    dp_wind         = Column(Float)             # wind power penalty (kW)
    dp_wave         = Column(Float)             # wave power penalty (kW)
    p_source        = Column(Float)             # raw power source (kW)
    p_corr          = Column(Float)             # ISO corrected delivered power (kW)

    # Stage 5 output
    v_exp_b1        = Column(Float)             # expected speed vs B1 baseline (kn)
    v_exp_b2        = Column(Float)             # expected speed vs B2 baseline (kn)
    speed_loss_b1   = Column(Float)             # speed loss % vs B1
    speed_loss_b2   = Column(Float)             # speed loss % vs B2 (main KPI input)

    data_source     = Column(String(20), default='mariapps')  # 'mariapps' or 'wni'

    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
