import logging
import time
import sys
import os
from playwright.sync_api import sync_playwright

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from backend.config import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

def run_automated_login():
    log.info("Starting background automated secure Microsoft SSO login...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True) # Keep False until login is 100% stable
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        # Add the visibility bypass
        context.add_init_script("""
            Object.defineProperty(document, 'visibilityState', { get: () => 'visible', configurable: true });
        """)

        log.info(f"Navigating to: {config.MARIAPPS_URL}")
        page.goto(config.MARIAPPS_URL, wait_until="domcontentloaded")
        
        # --- STEP 1: Aggressive "SIGN IN" click ---
        log.info("Looking for 'SIGN IN' gate button...")
        try:
            # Look for the exact Microsoft logo or the text 'SIGN IN'
            signin_btn = page.locator("text='SIGN IN'").first
            signin_btn.wait_for(state="visible", timeout=10000)
            signin_btn.click(force=True)
            log.info("  ↳ Successfully clicked gate SIGN IN.")
        except Exception as e:
            log.warning(f"  ↳ Could not find/click sign-in gate: {e}")
        
        # --- STEP 2: Email ---
        log.info("Waiting for Microsoft email input...")
        try:
            page.wait_for_selector("input[name='loginfmt'], #i0116", timeout=20000)
            page.locator("input[name='loginfmt'], #i0116").fill("pms@ozellar.com")
            page.locator("#idSIButton9").click()
            time.sleep(2)
        except Exception as e:
            log.error(f"Failed to enter email: {e}")
            browser.close(); return

        # --- STEP 3: Password ---
        log.info("Entering password...")
        try:
            page.wait_for_selector("input[name='passwd'], #i0118", timeout=10000)
            page.locator("input[name='passwd'], #i0118").fill("T%482550371780as")
            page.locator("#idSIButton9").click()
            time.sleep(2)
        except Exception as e:
            log.error(f"Failed to enter password: {e}")
            browser.close(); return
            
        # --- STEP 4: Stay Signed In ---
        log.info("Handling 'Stay signed in'...")
        try:
            page.wait_for_selector("#idSIButton9", timeout=5000)
            page.locator("#idSIButton9").click()
        except: pass
        
# --- REPLACE STEP 5 ---
        log.info("Waiting for successful Landing or LogApproval redirection...")
        try:
            # We wait for EITHER page instead of failing if it doesn't hit LogApproval
            page.wait_for_load_state("networkidle", timeout=30000)
            
            # Save the session regardless of which page we landed on
            context.storage_state(path=str(config.MARIAPPS_AUTH_JSON))
            log.info(f"SSO Session successfully created and saved to {config.MARIAPPS_AUTH_JSON}")
        except Exception as e:
            log.error(f"Redirection timed out: {e}")
            raise e

if __name__ == "__main__":
    run_automated_login()