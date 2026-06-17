import os
from datetime import datetime, timedelta
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import func
from ..database import SessionLocal
from ..models import DataQualityLog
import logging

# Configure logging
log = logging.getLogger(__name__)

# ============================================================
# WEEK LABEL CALCULATION
# ============================================================

def get_current_week_label(source_id="wni"):
    now = datetime.now()
    source_tag = str(source_id).upper()
    month = now.strftime('%b').upper()
    week_of_month = (now.day - 1) // 7 + 1
    year = now.year
    return f"{source_tag}-{month}-W{week_of_month}-{year}"

def get_previous_week_label(source_id="wni"):
    last_week = datetime.now() - timedelta(days=7)
    source_tag = str(source_id).upper()
    month = last_week.strftime('%b').upper()
    week_of_month = (last_week.day - 1) // 7 + 1
    year = last_week.year
    return f"{source_tag}-{month}-W{week_of_month}-{year}"

# ============================================================
# NEW: YTD DATA FETCHING
# ============================================================

def query_ytd_logs():
    """Fetches all quality issues since Jan 1st, 2026 for the Excel attachment."""
    db = SessionLocal()
    try:
        start_of_year = datetime(2026, 1, 1)
        return db.query(DataQualityLog).filter(
            DataQualityLog.report_date >= start_of_year
        ).order_by(DataQualityLog.vessel_name, DataQualityLog.report_date.desc()).all()
    finally:
        db.close()

def get_week_date_range(week_label):
    try:
        parts = week_label.split('-')
        month_str, week_num, year = parts[1], int(parts[2].replace('W', '')), int(parts[3])
        month_map = {'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
                     'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12}
        start_day = (week_num - 1) * 7 + 1
        start_date = datetime(year, month_map.get(month_str, 1), start_day)
        end_date = start_date + timedelta(days=6)
        return f"{start_date.strftime('%b %d')} - {end_date.strftime('%b %d, %Y')}"
    except: return "Date range unavailable"

def query_quality_logs(week_label):
    db = SessionLocal()
    try:
        source_display = week_label.split('-')[0] if '-' in week_label else "WNI"
        start_of_year = datetime(2026, 1, 1)

        # 1. Fetch Weekly Logs
        weekly_logs = db.query(DataQualityLog).filter(DataQualityLog.audit_period == week_label).all()
        
        # 2. Fetch YTD Logs (Since Jan 1st)
        ytd_logs = db.query(DataQualityLog).filter(DataQualityLog.report_date >= start_of_year).all()

        # Initialize data structure
        data = {
            "week_label": week_label,
            "source_name": source_display,
            "date_range": get_week_date_range(week_label),
            "total_issues": len(weekly_logs),
            "total_ytd": len(ytd_logs),
            "issues_by_type": {}, # Weekly
            "ytd_by_type": {},    # Yearly
            "issues_by_vessel": [],
            "details": [],
            "generated_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

        # Aggregate Weekly Stats
        for log_entry in weekly_logs:
            it = log_entry.issue_type or "UNKNOWN"
            data["issues_by_type"][it] = data["issues_by_type"].get(it, 0) + 1
            data["details"].append({
                "vessel": log_entry.vessel_name,
                "issue_type": log_entry.issue_type,
                "event_type": log_entry.event_type,
                "report_date": log_entry.report_date.strftime('%Y-%m-%d %H:%M'),
                "created_at": log_entry.created_at.strftime('%Y-%m-%d %H:%M')
            })

        # Aggregate YTD Stats by Type
        for log_entry in ytd_logs:
            it = log_entry.issue_type or "UNKNOWN"
            data["ytd_by_type"][it] = data["ytd_by_type"].get(it, 0) + 1

        # Aggregate Weekly Vessel Counts
        v_counts = {}
        for log_entry in weekly_logs:
            v_counts[log_entry.vessel_name] = v_counts.get(log_entry.vessel_name, 0) + 1
        data["issues_by_vessel"] = [{"vessel": v, "count": c} for v, c in sorted(v_counts.items(), key=lambda x: x[1], reverse=True)]

        return data
    finally:
        db.close()


def generate_html_report(data):
    try:
        template_dir = Path(__file__).parent / "templates"
        env = Environment(loader=FileSystemLoader(str(template_dir)))
        template = env.get_template("quality_report.html")
        return template.render(**data)
    except Exception as e:
        log.exception(f"Error generating HTML report: {e}")
        return None

def generate_weekly_report(week_label=None, use_previous_week=False):
    if week_label is None:
        week_label = get_previous_week_label() if use_previous_week else get_current_week_label()
    
    data = query_quality_logs(week_label)
    if data is None:
        return None
    
    return generate_html_report(data)