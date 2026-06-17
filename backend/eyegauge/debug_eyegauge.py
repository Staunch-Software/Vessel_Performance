import requests
import json
import logging
import sys
from pathlib import Path

# Setup paths to import config
current_dir = Path(__file__).resolve().parent
parent_dir = current_dir.parent
sys.path.append(str(parent_dir))
from config import config

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger()

class EyegaugeDebugger:
    def __init__(self):
        self.base_url = config.EYEGAUGE_BASE_URL.rstrip('/')
        self.token = self.get_token()
        self.headers = {
            "X-Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

    def get_token(self):
        url = f"{self.base_url}/api/auth/login"
        payload = {"username": config.EYEGAUGE_USERNAME, "password": config.EYEGAUGE_PASSWORD}
        try:
            res = requests.post(url, json=payload)
            res.raise_for_status()
            return res.json().get("token")
        except Exception as e:
            logger.error(f"Login Failed: {e}")
            sys.exit(1)

    def scan_everything(self):
        logger.info("="*60)
        logger.info("STARTING RAW DATA INSPECTION")
        logger.info("="*60)

        url = f"{self.base_url}/api/entitiesQuery/find"
        # We only need to look at DEVICEs to debug the structure
        payload = {
            "entityFilter": {"type": "entityType", "entityType": "DEVICE"},
            "pageLink": {"pageSize": 1, "page": 0}
        }
        
        try:
            res = requests.post(url, headers=self.headers, json=payload)
            if res.status_code == 200:
                data = res.json()
                items = data.get('data', [])
                
                if not items:
                    logger.error("No devices returned by API.")
                    return

                # --- THE IMPORTANT PART ---
                # We print the raw structure of the first item found
                first_item = items[0]
                logger.info("Successfully connected. Here is the RAW structure of your device:")
                logger.info("-" * 40)
                print(json.dumps(first_item, indent=4)) # Print pretty JSON
                logger.info("-" * 40)
                logger.info("Please copy the JSON above and paste it in the chat.")
                
            else:
                logger.error(f"API Error: {res.status_code} - {res.text}")
                
        except Exception as e:
            logger.error(f"Connection failed: {e}")

if __name__ == "__main__":
    debugger = EyegaugeDebugger()
    debugger.scan_everything()