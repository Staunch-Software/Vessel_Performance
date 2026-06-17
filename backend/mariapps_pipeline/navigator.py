import logging
from playwright.sync_api import Page

log = logging.getLogger(__name__)

class MariAppsNavigator:
    def __init__(self, page: Page):
        self.page = page
        self.target_url = "https://smartpal.ozellar.com/PerformancePALApp/Performance/LogApproval"

    def navigate_to_log_validation(self):
        log.info(f"Navigating to: {self.target_url}")
        # Wait for 'load' to ensure the base structure is there
        self.page.goto(self.target_url, wait_until="load", timeout=60000)
        
        # Check for session expiry
        if "Account/Index" in self.page.url or "Login" in self.page.url:
            log.error("Session expired. Please run generate_auth.py")
            raise Exception("Auth Required")
            
        # Wait for the vessel search box to be present before starting the loop
        self.page.wait_for_selector("input[aria-owns='vesselSearchBox_listbox']", timeout=30000)