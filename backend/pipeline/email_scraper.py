import os
import io
import re
import base64
import requests
from dotenv import load_dotenv
import pandas as pd
import logging
from backend.excel_processing.tufmax_parser import parse_tufmax_excel
from backend.pipeline.processor import save_to_db
from backend.database import SessionLocal
from backend.models import Vessel, ProcessedEmail

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logging.getLogger("urllib3").setLevel(logging.WARNING)

load_dotenv()

AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID")
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
IMAP_EMAIL = os.getenv("IMAP_EMAIL")

def get_access_token():
    """Obtain OAuth2 token from Microsoft Graph using Client Credentials."""
    if not all([AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET]):
        logger.error("Azure Graph API credentials missing in .env")
        return None

    url = f"https://login.microsoftonline.com/{AZURE_TENANT_ID}/oauth2/v2.0/token"
    payload = {
        "client_id": AZURE_CLIENT_ID,
        "scope": "https://graph.microsoft.com/.default",
        "client_secret": AZURE_CLIENT_SECRET,
        "grant_type": "client_credentials"
    }
    
    response = requests.post(url, data=payload)
    if response.status_code == 200:
        return response.json().get("access_token")
    else:
        logger.error(f"Failed to get access token: {response.text}")
        return None

def parse_email_body(body_text):
    """
    Parses the plain text body to extract:
    - Voyage Number (e.g. 'VOY 104')
    - Wave/Swell height in meters (e.g. 'SWELL – SW X 1 MTRS' -> 1.0)
    """
    voyage_no = ""
    wave_height_m = None

    # Extract Voyage Number
    match = re.search(r"VOY\s+(\d+)", body_text, re.IGNORECASE)
    if match:
        voyage_no = match.group(1)

    # Extract Swell/Wave height in meters from patterns like:
    # 'SWELL – SW X 1 MTRS', 'SWELL- 1.5M', 'WAVE HT 2 M', 'SWELL 1 MTR'
    wave_patterns = [
        r"SWELL[^\d]*(\d+\.?\d*)\s*(?:MTRS?|M\b)",
        r"WAVE\s*H[T]?[^\d]*(\d+\.?\d*)\s*(?:MTRS?|M\b)",
        r"SWL[^\d]*(\d+\.?\d*)\s*(?:MTRS?|M\b)",
    ]
    for pattern in wave_patterns:
        m = re.search(pattern, body_text, re.IGNORECASE)
        if m:
            try:
                wave_height_m = float(m.group(1))
                break
            except ValueError:
                pass

    return {"voyage_no": voyage_no, "wave_height_m": wave_height_m}

def update_wave_height_from_body(voyage_no, wave_height_m):
    """
    When an email has no .xlsx attachment (reply-only), but the body contains
    wave height data, update all existing noon_report_data records for that
    voyage with the new wave height value from the email body.
    Uses file_name in raw_noon_reports to match the voyage number.
    """
    if not voyage_no or wave_height_m is None:
        return 0

    from sqlalchemy import text
    db = SessionLocal()
    try:
        # Find all raw_noon_report IDs for this voyage
        # file_name is stored as 'email_voyage_104' format
        raw_ids = db.execute(text("""
            SELECT id FROM raw_noon_reports
            WHERE vessel_imo = '9486295'
              AND file_name = :fname
        """), {"fname": f"email_voyage_{voyage_no}"}).fetchall()

        raw_id_list = [r[0] for r in raw_ids]
        if not raw_id_list:
            return 0

        # Update wave_height in noon_report_data for those raw report ids
        result = db.execute(text("""
            UPDATE noon_report_data
            SET wave_height = :wh
            WHERE raw_report_id = ANY(:ids)
              AND (wave_height IS NULL OR CAST(wave_height AS NUMERIC) != :wh)
        """), {"wh": wave_height_m, "ids": raw_id_list})
        db.commit()
        return result.rowcount
    except Exception as e:
        db.rollback()
        logger.error(f"  [ERROR] Failed to update wave height: {e}")
        return 0
    finally:
        db.close()


def process_email_attachment(attachment_data, email_data):
    """
    Passes the in-memory excel file to the parser and merges data from email body.
    email_data: dict with keys 'voyage_no' and 'wave_height_m'
    """
    voyage_no = email_data.get("voyage_no", "")
    wave_height_m = email_data.get("wave_height_m")  # None if not found in body

    try:
        temp_path = "temp_tufmax_email.xlsx"
        with open(temp_path, "wb") as f:
            f.write(attachment_data)
            
        records = parse_tufmax_excel(temp_path)
        
        # Merge email body data into every record
        for record in records:
            # Voyage Number
            if not record.get("Voyage Number_#") and voyage_no:
                record["Voyage Number_#"] = voyage_no
            # Wave height: use email body value if available, else keep Excel fallback
            if wave_height_m is not None:
                record["Wave (WNI)_Sig. Wave (m)"] = wave_height_m
                
        # Save to DB
        db = SessionLocal()
        vessel = db.query(Vessel).filter(Vessel.vessel_name == "AMNS TUFMAX").first()
        
        saved_count = 0
        dup_count = 0
        error_count = 0
        
        if vessel:
            for record in records:
                date_str = record.get("Date")
                if date_str:
                    # save_to_db returns "success", "duplicate", or "error"
                    res = save_to_db(vessel.vessel_name, record, f"email_voyage_{voyage_no}")
                    if res == "success":
                        saved_count += 1
                    elif res == "duplicate":
                        dup_count += 1
                    else:
                        error_count += 1
            
            logger.info(f"Excel Processed: {len(records)} total rows found | {saved_count} new saved | {dup_count} duplicates skipped.")
        else:
            logger.error("Vessel 'AMNS TUFMAX' not found in database!")
            
        db.close()
        
        # Store the Excel file permanently instead of deleting it
        from backend.config import config
        reports_dir = os.path.join(config.ROOT_DIR, "data", "tufmax_reports")
        os.makedirs(reports_dir, exist_ok=True)
        
        # Find the date of the report for naming
        report_date = None
        for r in records:
            if r.get("Date"):
                report_date = str(r["Date"]).replace(" ", "_").replace(":", "-").replace("/", "-")
                break
                
        if report_date:
            filename = f"AMNS_TUFMAX_Voyage_{voyage_no}_{report_date}.xlsx"
        else:
            import time
            filename = f"AMNS_TUFMAX_Voyage_{voyage_no}_{int(time.time())}.xlsx"
            
        perm_path = os.path.join(reports_dir, filename)
        
        import shutil
        if os.path.exists(temp_path):
            shutil.move(temp_path, perm_path)
            logger.info(f"Stored original Excel file permanently at {perm_path}")
            
        return True
    except Exception as e:
        logger.error(f"Error processing attachment: {e}")
        return False

def check_inbox(force_full_run=False):
    if not IMAP_EMAIL:
        logger.error("IMAP_EMAIL missing in .env")
        return
        
    token = get_access_token()
    if not token:
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }

    # Start with the first page of up to 100 emails, filtered by subject
    url = f"https://graph.microsoft.com/v1.0/users/{IMAP_EMAIL}/mailFolders/inbox/messages?$filter=contains(subject, 'TUFMAX') and contains(subject, 'NOON')&$orderby=receivedDateTime DESC&$top=100"
    
    total_emails_scanned = 0
    total_with_attachment = 0
    total_no_cc = 0
    total_no_attachment = 0
    total_bad_body = 0
    new_processed_count = 0
    stop_pagination = False
    
    while url and not stop_pagination:
        try:
            response = requests.get(url, headers=headers)
            if response.status_code != 200:
                logger.error(f"Failed to fetch emails: {response.text}")
                break
                
            data = response.json()
            messages = data.get("value", [])
            total_emails_scanned += len(messages)
            logger.info(f"──── Scanning page of {len(messages)} emails (Total scanned: {total_emails_scanned}) ────")
            
            for msg in messages:
                msg_id = msg.get("id")
                subject = msg.get("subject", "")
                subject_upper = subject.upper()
                cc_recipients = msg.get("ccRecipients", [])
    
                # ── STEP 1: Subject Filter (case-insensitive) ─────────────────────
                if "NOON REPORT" not in subject_upper or "TUFMAX" not in subject_upper:
                    continue   # silently skip — too many irrelevant emails to log
    
                # ── STEP 2: Duplicate MSG ID Check ───────────────────────────────
                _db = SessionLocal()
                try:
                    already_done = _db.query(ProcessedEmail).filter(
                        ProcessedEmail.msg_id == msg_id
                    ).first()
                finally:
                    _db.close()
    
                if already_done:
                    if force_full_run:
                        logger.info(f"  [SKIP] Already processed: \"{subject}\"")
                        continue
                    else:
                        logger.info(f"  [STOP] Reached already-processed email. Stopping search.")
                        stop_pagination = True
                        break
    
                # ── STEP 3: CC Filter ────────────────────────────────────────────
                cc_addresses = [
                    cc.get("emailAddress", {}).get("address", "").lower()
                    for cc in cc_recipients
                ]
                if "tmamnstufmax@ozellar.com" not in cc_addresses:
                    total_no_cc += 1
                    logger.info(f"  [SKIP] No required CC address: \"{subject}\"")
                    continue
    
                # ── STEP 4: Parse Body for Voyage No & Wave Height ───────────────
                body_text = msg.get("body", {}).get("content", "")
                email_data = parse_email_body(body_text)
                voyage_no = email_data.get("voyage_no", "N/A")
                wave_ht   = email_data.get("wave_height_m", "N/A")

                if not voyage_no or voyage_no == "N/A":
                    total_bad_body += 1
                    logger.warning(f"  [SKIP] Body has no Voyage No: \"{subject}\"")
                    continue

                logger.info(f"  [MATCH] \"{subject}\" | Voyage: {voyage_no} | Wave: {wave_ht}m")
    
                # ── STEP 5: Fetch & Check for .xlsx Attachment ───────────────────
                attachments_url = f"https://graph.microsoft.com/v1.0/users/{IMAP_EMAIL}/messages/{msg_id}/attachments"
                att_res = requests.get(attachments_url, headers=headers)
    
                if att_res.status_code != 200:
                    logger.error(f"  [ERROR] Could not fetch attachments: {att_res.text}")
                    continue

                attachments = att_res.json().get("value", [])
                excel_attachment = next((a for a in attachments if a.get("name", "").endswith(".xlsx")), None)
    
                if not excel_attachment:
                    total_no_attachment += 1
                    # Even without Excel, try to update wave height from body
                    if wave_ht and wave_ht != "N/A" and voyage_no:
                        updated = update_wave_height_from_body(voyage_no, wave_ht)
                        if updated > 0:
                            logger.info(f"  [BODY UPDATE] No .xlsx, but updated wave_height={wave_ht}m for {updated} record(s) in Voyage {voyage_no}.")
                        else:
                            logger.info(f"  [SKIP] No .xlsx attachment and no matching DB records to update for Voyage {voyage_no}.")
                    else:
                        logger.info(f"  [SKIP] No .xlsx attachment and no wave data in body.")
                    continue

                # ── STEP 6: Decode & Process Excel ───────────────────────────────
                content_b64 = excel_attachment.get("contentBytes")
                if not content_b64:
                    logger.warning(f"  [SKIP] Attachment '{excel_attachment.get('name')}' has no content.")
                    continue

                total_with_attachment += 1
                attachment_data = base64.b64decode(content_b64)
                success = process_email_attachment(attachment_data, email_data)
    
                if success:
                    # Save MSG ID so this email is never re-processed
                    _db2 = SessionLocal()
                    try:
                        _db2.add(ProcessedEmail(
                            msg_id=msg_id,
                            subject=subject,
                            vessel_name="AMNS TUFMAX"
                        ))
                        _db2.commit()
                        new_processed_count += 1
                    except Exception as _e:
                        _db2.rollback()
                        logger.warning(f"  [WARN] Could not save msg_id to processed_emails: {_e}")
                    finally:
                        _db2.close()

                    # Mark email as read
                    patch_url = f"https://graph.microsoft.com/v1.0/users/{IMAP_EMAIL}/messages/{msg_id}"
                    requests.patch(patch_url, headers=headers, json={"isRead": True})
                else:
                    logger.error(f"  [ERROR] Failed to process Excel attachment for: \"{subject}\"")
                
        # (End of message loop)
            
            if stop_pagination:
                break

            # Get the next page URL if it exists
            url = data.get("@odata.nextLink")
                    
        except Exception as e:
            logger.error(f"Graph API Error during pagination: {e}")
            break
            
    logger.info("════════════════════════════════════════════════════")
    logger.info(f"  SCAN COMPLETE")
    logger.info(f"  Total emails scanned      : {total_emails_scanned}")
    logger.info(f"  Matched subject + CC      : {total_with_attachment + total_no_attachment + total_bad_body}")
    logger.info(f"  Skipped (no CC address)   : {total_no_cc}")
    logger.info(f"  Skipped (no body data)    : {total_bad_body}")
    logger.info(f"  Skipped (no .xlsx attach) : {total_no_attachment}")
    logger.info(f"  Excel files processed     : {total_with_attachment}")
    logger.info(f"  New emails saved to DB    : {new_processed_count}")
    logger.info("════════════════════════════════════════════════════")

if __name__ == "__main__":
    import sys
    is_full_run = "--full" in sys.argv
    if is_full_run:
        logger.info("Running in FULL search mode. Will not stop on already-processed emails.")
    check_inbox(force_full_run=is_full_run)
