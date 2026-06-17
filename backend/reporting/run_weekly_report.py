import sys
import argparse
import logging
import pandas as pd
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.config import config
from backend.reporting.report_generator import generate_weekly_report, get_current_week_label, query_ytd_logs
from backend.reporting.email_service import send_email

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        # FIXED: Now points to logs/weekly_report.log using config
        logging.FileHandler(config.WEEKLY_LOG, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

def create_ytd_excel(logs):
    """
    Requirement 4: Multi-tab Excel
    - Tab 1: Generic Analytics (Issues since Jan 1st)
    - Tab 2-N: Individual Vessel Logs
    """
    if not logs:
        log.warning("No YTD logs found to create Excel.")
        return None

    # 1. Format data for Pandas
    data = []
    for l in logs:
        data.append({
            "Vessel Name": l.vessel_name,
            "Vessel IMO": l.vessel_imo,
            "Issue Type": l.issue_type,
            "Event Type": l.event_type,
            "Report Date": l.report_date.strftime('%Y-%m-%d %H:%M') if l.report_date else "N/A",
            "Audit Period": l.audit_period,
            "Source": l.source_id.upper() if l.source_id else "WNI"
        })
    
    df = pd.DataFrame(data)
    # Target filename
    ytd_file = Path(__file__).parent.parent / f"Data_Quality_Audit_YTD_2026.xlsx"

    # 2. Write Multi-Tab Excel
    with pd.ExcelWriter(ytd_file, engine='openpyxl') as writer:
        # --- TAB 1: GENERIC ANALYTICS ---
        # Grouping by Vessel Name to show total issues found since 1st Jan
        summary_df = df.groupby("Vessel Name").size().reset_index(name="Total Issues Since Jan 1, 2026")
        summary_df.to_excel(writer, sheet_name="Fleet Analytics", index=False)

        # --- TABS 2-N: INDIVIDUAL VESSELS ---
        for vessel in df["Vessel Name"].unique():
            vessel_df = df[df["Vessel Name"] == vessel]
            # Excel sheet names have a 31 character limit and cannot contain special chars
            sheet_name = str(vessel)[:31].replace("/", "-").replace("[", "").replace("]", "")
            vessel_df.to_excel(writer, sheet_name=sheet_name, index=False)

    log.info(f"YTD Excel created with {len(df['Vessel Name'].unique()) + 1} tabs.")
    return str(ytd_file)

def main():
    parser = argparse.ArgumentParser(description="Generate and email weekly data quality report")
    parser.add_argument("--previous-week", action="store_true")
    parser.add_argument("--week", type=str)
    parser.add_argument("--save-only", action="store_true")
    args = parser.parse_args()
    
    print("\n" + "="*75)
    print("DATA QUALITY AUDIT - WNI SOURCE")
    print("="*75)
    
    # ---- 1. DETERMINE WEEK ----
    is_monday = datetime.now().weekday() == 0
    if args.week:
        week_label = args.week
    elif args.previous_week or is_monday:
        week_label = None  # Previous week logic
    else:
        week_label = get_current_week_label()

    # ---- 2. GENERATE HTML DASHBOARD ----
    print("\n📊 Generating HTML Dashboard...")
    html_content = generate_weekly_report(
        week_label=week_label,
        use_previous_week=(args.previous_week or is_monday)
    )
    
    # ---- 3. GENERATE YTD EXCEL (SINCE JAN 1) ----
    print("📂 Fetching YTD Audit History...")
    ytd_logs = query_ytd_logs() # Ensure this function filters from Jan 1, 2026
    excel_path = create_ytd_excel(ytd_logs)

    # ---- 4. SAVE TO FILE (FOR PREVIEW) ----
    if args.save_only:
        output_path = Path(__file__).parent.parent / "quality_report_preview.html"
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"✅ Dashboard Preview: {output_path}")
        print(f"✅ Excel Preview: {excel_path}")
        return

    # ---- 5. SEND EMAIL ----
    source_tag = "WNI" # Clearly define the source
    subject_week = week_label if week_label else "Weekly Update"
    
    print(f"\n📧 Sending {source_tag} Dashboard email...")
    
    success = send_email(
        subject=f"{source_tag} Data Quality Report - {subject_week}",
        html_content=html_content,
        attachments=[excel_path] if excel_path else None
    )
    
    if success:
        print("✅ Weekly report sent successfully with YTD history.")
    else:
        print("❌ Failed to send email.")
        sys.exit(1)

if __name__ == "__main__":
    main()