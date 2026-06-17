import logging
from playwright.sync_api import sync_playwright
from ..config import config

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

def generate_session():
    # Run this LOCALLY (not on the server) to produce auth.json, then upload it to the VM.
    log.info("Starting browser for manual login...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        # INCREASED TIMEOUT and changed wait strategy
        log.info(f"Navigating to: {config.MARIAPPS_URL}")
        try:
            page.goto(config.MARIAPPS_URL, wait_until="domcontentloaded", timeout=90000)
        except Exception as e:
            log.warning(f"Initial load timed out, but proceeding to manual login: {e}")

        print("\n" + "="*50)
        print("ACTION REQUIRED:")
        print("1. Please log in to MariApps manually.")
        print("2. Complete SSO/MFA.")
        print("3. Once you see the Dashboard, press ENTER here.")
        print("="*50 + "\n")

        input("Press ENTER here after successful login...")

        auth_path = config.MARIAPPS_AUTH_JSON
        context.storage_state(path=str(auth_path))
        log.info(f"Successfully saved auth session to: {auth_path}")
        browser.close()

if __name__ == "__main__":
    generate_session()