"""
debug_voyage.py
===============
Scans ALL telemetry keys from the Eyegauge ASSET and all DEVICEs
to find if voyage number exists anywhere in the data.

Run:
    python backend\eyegauge\debug_voyage.py
"""

import logging
import sys
import json
import requests
from pathlib import Path
from datetime import datetime, timezone, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
logger = logging.getLogger(__name__)

current_dir  = Path(__file__).resolve().parent
backend_dir  = current_dir.parent
project_root = backend_dir.parent
for p in (backend_dir, project_root):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

try:
    from config import config
except ModuleNotFoundError:
    from backend.config import config

BASE_URL  = config.EYEGAUGE_BASE_URL.rstrip("/")
USERNAME  = config.EYEGAUGE_USERNAME
PASSWORD  = config.EYEGAUGE_PASSWORD
VESSEL_IMO = "9832913"

VOYAGE_HINTS = ["voyage", "trip", "leg", "port", "from", "to", "depart", "arriv"]

def get_token():
    res = requests.post(f"{BASE_URL}/api/auth/login",
                        json={"username": USERNAME, "password": PASSWORD})
    res.raise_for_status()
    return res.json()["token"]

def headers(token):
    return {"X-Authorization": f"Bearer {token}", "Content-Type": "application/json"}

def get_asset(token):
    """Find the ASSET for our vessel by IMO."""
    page = 0
    while True:
        res = requests.get(f"{BASE_URL}/api/user/assets?pageSize=20&page={page}",
                           headers=headers(token))
        data = res.json()
        for asset in data.get("data", []):
            asset_id = asset["id"]["id"]
            # check imo attribute
            attr_res = requests.get(
                f"{BASE_URL}/api/plugins/telemetry/ASSET/{asset_id}/values/attributes",
                headers=headers(token)
            )
            for attr in attr_res.json():
                if attr.get("key") == "imo" and str(attr.get("value", "")).strip() == VESSEL_IMO:
                    return asset_id, asset.get("name")
        if not data.get("hasNext"):
            break
        page += 1
    return None, None

def get_timeseries_keys(token, entity_type, entity_id):
    res = requests.get(
        f"{BASE_URL}/api/plugins/telemetry/{entity_type}/{entity_id}/keys/timeseries",
        headers=headers(token)
    )
    return res.json() if res.status_code == 200 else []

def get_sample_values(token, entity_type, entity_id, keys):
    """Get latest values for given keys."""
    end_ts   = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ts = int((datetime.now(timezone.utc) - timedelta(days=7)).timestamp() * 1000)
    key_str  = ",".join(keys[:20])  # limit to 20 at a time
    res = requests.get(
        f"{BASE_URL}/api/plugins/telemetry/{entity_type}/{entity_id}/values/timeseries"
        f"?keys={key_str}&startTs={start_ts}&endTs={end_ts}&limit=1&agg=NONE",
        headers=headers(token)
    )
    return res.json() if res.status_code == 200 else {}

def main():
    logger.info("Logging in ...")
    token = get_token()

    logger.info("Finding vessel ASSET ...")
    asset_id, asset_name = get_asset(token)
    if not asset_id:
        logger.error("Vessel not found.")
        return
    logger.info(f"Vessel: {asset_name} | asset_id: {asset_id}")

    # ── Scan ASSET telemetry keys ──────────────────────────────────────────────
    logger.info("\n" + "="*60)
    logger.info("ASSET TELEMETRY KEYS:")
    logger.info("="*60)
    asset_keys = get_timeseries_keys(token, "ASSET", asset_id)
    logger.info(f"Total keys: {len(asset_keys)}")
    logger.info(f"All keys: {sorted(asset_keys)}")

    voyage_keys = [k for k in asset_keys if any(h in k.lower() for h in VOYAGE_HINTS)]
    if voyage_keys:
        logger.info(f"\n>>> VOYAGE-RELATED KEYS FOUND IN ASSET: {voyage_keys}")
        sample = get_sample_values(token, "ASSET", asset_id, voyage_keys)
        logger.info(f"Sample values: {json.dumps(sample, indent=2)}")
    else:
        logger.warning("No voyage-related keys found in ASSET telemetry.")

    # ── Scan all DEVICE telemetry keys ─────────────────────────────────────────
    rel_res = requests.get(
        f"{BASE_URL}/api/relations?fromId={asset_id}&fromType=ASSET&relationType=Contains",
        headers=headers(token)
    )
    relations = rel_res.json() if rel_res.status_code == 200 else []

    for rel in relations:
        device_id = rel.get("to", {}).get("id")
        if not device_id:
            continue
        dev_res = requests.get(f"{BASE_URL}/api/device/{device_id}", headers=headers(token))
        dev_name = dev_res.json().get("name", device_id) if dev_res.status_code == 200 else device_id
        dev_type = dev_res.json().get("type", "") if dev_res.status_code == 200 else ""

        dev_keys = get_timeseries_keys(token, "DEVICE", device_id)
        voyage_dev_keys = [k for k in dev_keys if any(h in k.lower() for h in VOYAGE_HINTS)]

        if voyage_dev_keys:
            logger.info(f"\n>>> VOYAGE-RELATED KEYS FOUND IN DEVICE '{dev_name}' ({dev_type}): {voyage_dev_keys}")
            sample = get_sample_values(token, "DEVICE", device_id, voyage_dev_keys)
            logger.info(f"Sample values: {json.dumps(sample, indent=2)}")

    logger.info("\n" + "="*60)
    logger.info("CONCLUSION:")
    logger.info("If no voyage keys were found above, Eyegauge does not")
    logger.info("send voyage number — it must be entered manually.")
    logger.info("="*60)

if __name__ == "__main__":
    main()