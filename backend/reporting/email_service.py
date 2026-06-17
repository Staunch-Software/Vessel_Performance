# ============================================================
# EMAIL SERVICE MODULE
# ============================================================
# Purpose: Send HTML emails via Azure AD (Microsoft 365) or SMTP
# 
# Supports:
# - Azure AD OAuth 2.0 authentication (Microsoft 365/Office 365)
# - Standard SMTP (Gmail, etc.)
# - Auto-detects method based on environment variables
# ============================================================

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
log = logging.getLogger(__name__)


# ============================================================
# EMAIL CONFIGURATION
# ============================================================

class EmailConfig:
    """
    Email configuration class
    Auto-detects Azure AD or SMTP based on environment variables
    """
    
    # Azure AD Settings (Microsoft 365)
    AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID")
    AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
    AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
    
    # Standard SMTP Settings
    MAIL_USERNAME = os.getenv("MAIL_USERNAME")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
    MAIL_HOST = os.getenv("MAIL_HOST", "smtp.gmail.com")
    MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
    
    # Common Settings
    MAIL_FROM = os.getenv("MAIL_FROM")
    MAIL_FROM_NAME = os.getenv("MAIL_FROM_NAME", "Maritime Noon Report System")
    
    # Recipients (comma-separated)
    MAIL_TO = os.getenv("MAIL_TO", "").split(",")
    MAIL_CC = os.getenv("MAIL_CC", "").split(",") if os.getenv("MAIL_CC") else []
    
    @classmethod
    def is_azure_ad_configured(cls):
        """Check if Azure AD credentials are configured"""
        return all([
            cls.AZURE_TENANT_ID,
            cls.AZURE_CLIENT_ID,
            cls.AZURE_CLIENT_SECRET,
            cls.MAIL_FROM
        ])
    
    @classmethod
    def is_smtp_configured(cls):
        """Check if SMTP credentials are configured"""
        return all([
            cls.MAIL_USERNAME,
            cls.MAIL_PASSWORD,
            cls.MAIL_FROM
        ])


# ============================================================
# AZURE AD EMAIL SENDER (Microsoft 365)
# ============================================================

def send_email_azure_ad(subject, html_content, recipients, cc_recipients=None, attachments=None):
    """
    Send email using Azure AD OAuth 2.0 (Microsoft 365)
    
    Args:
        subject: Email subject line
        html_content: HTML body content
        recipients: List of recipient email addresses
        cc_recipients: List of CC email addresses (optional)
        attachments: List of file paths to attach (optional)
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        from msal import ConfidentialClientApplication
        import requests
        
        log.info("Sending email via Azure AD (Microsoft 365)")
        
        # ---- STEP 1: Acquire Access Token ----
        authority = f"https://login.microsoftonline.com/{EmailConfig.AZURE_TENANT_ID}"
        app = ConfidentialClientApplication(
            EmailConfig.AZURE_CLIENT_ID,
            authority=authority,
            client_credential=EmailConfig.AZURE_CLIENT_SECRET
        )
        
        # Request token with Microsoft Graph API scope
        result = app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )
        
        if "access_token" not in result:
            log.error(f"Failed to acquire token: {result.get('error_description')}")
            return False
        
        access_token = result["access_token"]
        
        # ---- STEP 2: Prepare Email Message ----
        # Clean recipient lists
        to_recipients = [{"emailAddress": {"address": r.strip()}} for r in recipients if r.strip()]
        cc_list = [{"emailAddress": {"address": r.strip()}} for r in (cc_recipients or []) if r.strip()]
        
        # Build email payload
        email_msg = {
            "message": {
                "subject": subject,
                "body": {
                    "contentType": "HTML",
                    "content": html_content
                },
                "toRecipients": to_recipients,
                "ccRecipients": cc_list if cc_list else []
            },
            "saveToSentItems": "true"
        }
        
        # ---- STEP 3: Send Email via Microsoft Graph API ----
        endpoint = f"https://graph.microsoft.com/v1.0/users/{EmailConfig.MAIL_FROM}/sendMail"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        response = requests.post(endpoint, headers=headers, json=email_msg)
        
        if response.status_code == 202:
            log.info(f"✅ Email sent successfully via Azure AD to {len(to_recipients)} recipients")
            return True
        else:
            log.error(f"❌ Failed to send email: {response.status_code} - {response.text}")
            return False
            
    except ImportError:
        log.error("❌ 'msal' library not installed. Run: pip install msal requests")
        return False
    except Exception as e:
        log.exception(f"❌ Error sending email via Azure AD: {e}")
        return False


# ============================================================
# SMTP EMAIL SENDER (Gmail, etc.)
# ============================================================

def send_email_smtp(subject, html_content, recipients, cc_recipients=None, attachments=None):
    """
    Send email using standard SMTP
    
    Args:
        subject: Email subject line
        html_content: HTML body content
        recipients: List of recipient email addresses
        cc_recipients: List of CC email addresses (optional)
        attachments: List of file paths to attach (optional)
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        log.info("Sending email via SMTP")
        
        # ---- STEP 1: Create Message ----
        msg = MIMEMultipart('alternative')
        msg['From'] = f"{EmailConfig.MAIL_FROM_NAME} <{EmailConfig.MAIL_FROM}>"
        msg['To'] = ", ".join([r.strip() for r in recipients if r.strip()])
        msg['Subject'] = subject
        
        # Add CC if provided
        if cc_recipients:
            cc_list = [r.strip() for r in cc_recipients if r.strip()]
            if cc_list:
                msg['Cc'] = ", ".join(cc_list)
        
        # ---- STEP 2: Attach HTML Content ----
        html_part = MIMEText(html_content, 'html', 'utf-8')
        msg.attach(html_part)
        
        # ---- STEP 3: Attach Files (if any) ----
        if attachments:
            for file_path in attachments:
                if os.path.exists(file_path):
                    with open(file_path, 'rb') as f:
                        part = MIMEBase('application', 'octet-stream')
                        part.set_payload(f.read())
                        encoders.encode_base64(part)
                        part.add_header(
                            'Content-Disposition',
                            f'attachment; filename={os.path.basename(file_path)}'
                        )
                        msg.attach(part)
        
        # ---- STEP 4: Connect to SMTP Server ----
        with smtplib.SMTP(EmailConfig.MAIL_HOST, EmailConfig.MAIL_PORT) as server:
            server.starttls()  # Enable TLS encryption
            server.login(EmailConfig.MAIL_USERNAME, EmailConfig.MAIL_PASSWORD)
            
            # Combine TO and CC for actual sending
            all_recipients = [r.strip() for r in recipients if r.strip()]
            if cc_recipients:
                all_recipients.extend([r.strip() for r in cc_recipients if r.strip()])
            
            # Send email
            server.send_message(msg)
            
        log.info(f"✅ Email sent successfully via SMTP to {len(all_recipients)} recipients")
        return True
        
    except Exception as e:
        log.exception(f"❌ Error sending email via SMTP: {e}")
        return False


# ============================================================
# UNIFIED EMAIL SENDER (AUTO-DETECT METHOD)
# ============================================================

def send_email(subject, html_content, recipients=None, cc_recipients=None, attachments=None):
    """
    Send email using available method (Azure AD or SMTP)
    Auto-detects which method to use based on configuration
    
    Args:
        subject: Email subject line
        html_content: HTML body content
        recipients: List of recipient emails (uses MAIL_TO from .env if None)
        cc_recipients: List of CC emails (uses MAIL_CC from .env if None)
        attachments: List of file paths to attach (optional)
        
    Returns:
        bool: True if successful, False otherwise
    """
    
    # Use default recipients from config if not provided
    if recipients is None:
        recipients = EmailConfig.MAIL_TO
    
    if cc_recipients is None:
        cc_recipients = EmailConfig.MAIL_CC
    
    # Validate recipients
    recipients = [r.strip() for r in recipients if r and r.strip()]
    if not recipients:
        log.error("❌ No recipients specified")
        return False
    
    # ---- AUTO-DETECT EMAIL METHOD ----
    if EmailConfig.is_azure_ad_configured():
        log.info("Using Azure AD (Microsoft 365) for email")
        return send_email_azure_ad(subject, html_content, recipients, cc_recipients, attachments)
    
    elif EmailConfig.is_smtp_configured():
        log.info("Using SMTP for email")
        return send_email_smtp(subject, html_content, recipients, cc_recipients, attachments)
    
    else:
        log.error("❌ No email configuration found. Please configure Azure AD or SMTP in .env file")
        return False


# ============================================================
# TEST FUNCTION
# ============================================================

def test_email_configuration():
    """
    Test email configuration by sending a test email
    """
    test_html = """
    <html>
        <body style="font-family: Arial, sans-serif;">
            <h2 style="color: #2c5aa0;">✅ Email Configuration Test</h2>
            <p>This is a test email from the Maritime Noon Report System.</p>
            <p>If you received this, your email configuration is working correctly!</p>
            <hr>
            <p style="color: #666; font-size: 12px;">
                Generated by Maritime Noon Report System
            </p>
        </body>
    </html>
    """
    
    print("\n" + "="*60)
    print("EMAIL CONFIGURATION TEST")
    print("="*60)
    
    if EmailConfig.is_azure_ad_configured():
        print("✅ Azure AD configuration detected")
        print(f"   Tenant ID: {EmailConfig.AZURE_TENANT_ID}")
        print(f"   Client ID: {EmailConfig.AZURE_CLIENT_ID}")
        print(f"   From: {EmailConfig.MAIL_FROM}")
    elif EmailConfig.is_smtp_configured():
        print("✅ SMTP configuration detected")
        print(f"   Host: {EmailConfig.MAIL_HOST}:{EmailConfig.MAIL_PORT}")
        print(f"   Username: {EmailConfig.MAIL_USERNAME}")
        print(f"   From: {EmailConfig.MAIL_FROM}")
    else:
        print("❌ No email configuration found!")
        print("\nPlease add to .env file:")
        print("\nFor Azure AD:")
        print("  AZURE_TENANT_ID=your-tenant-id")
        print("  AZURE_CLIENT_ID=your-client-id")
        print("  AZURE_CLIENT_SECRET=your-secret")
        print("  MAIL_FROM=your-email@company.com")
        print("\nFor SMTP:")
        print("  MAIL_USERNAME=your-email@gmail.com")
        print("  MAIL_PASSWORD=your-app-password")
        print("  MAIL_FROM=your-email@gmail.com")
        return
    
    print(f"\nRecipients: {EmailConfig.MAIL_TO}")
    print("\nSending test email...")
    
    success = send_email(
        subject="🧪 Email Configuration Test",
        html_content=test_html
    )
    
    if success:
        print("\n✅ Test email sent successfully!")
    else:
        print("\n❌ Failed to send test email. Check logs for details.")
    
    print("="*60 + "\n")


# ============================================================
# DIRECT EXECUTION
# ============================================================

if __name__ == "__main__":
    # Configure logging for standalone execution
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    
    test_email_configuration()
