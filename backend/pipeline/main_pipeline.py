# ============================================================
# WNI AUTOMATED DATA PIPELINE
# ============================================================
# Purpose: Automated daily download of vessel noon reports from WNI portal
# 
# Process Flow:
# 1. Login to Weathernews portal using Playwright
# 2. Navigate to Logbook+ section
# 3. For each vessel in vessels.txt:
#    - Select vessel
#    - Set date filters to yesterday
#    - Download CSV report
#    - Parse multi-row headers
#    - Save to database
# 4. Log all operations for audit trail
# ============================================================

import os
import pandas as pd
import numpy as np
import re
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from ..config import config
from ..database import init_db
from .processor import save_to_db
import logging
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# LOGGING CONFIGURATION
# ============================================================

load_dotenv()

LOG_FILE = config.PIPELINE_LOG

# 2. Configure logging: Using the centralized path and UTF-8 for Windows safety
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'), # Saves to logs/ folder
        logging.StreamHandler() # Also prints to your terminal
    ]
)

log = logging.getLogger(__name__)


# ============================================================
# CSV HEADER PROCESSING
# ============================================================

def clean_header(text):
    """
    Cleans Excel/CSV header text by removing formatting artifacts
    
    Removes:
    - Excel line break codes (_x000D_)
    - Newline and carriage return characters
    - Extra whitespace
    - Quotes and special characters
    
    Args:
        text: Raw header text from CSV
        
    Returns:
        Cleaned header string
    """
    text = str(text)

    # Remove Excel garbage characters
    text = text.replace("_x000D_", " ")
    text = text.replace("\n", " ")
    text = text.replace("\r", " ")

    # Normalize spacing (collapse multiple spaces)
    text = re.sub(r"\s+", " ", text)

    # Strip quotes and junk
    text = text.strip(" '\"")

    return text.strip()


def get_wni_headers(temp_csv):
    """
    Extracts and constructs proper column headers from WNI CSV files
    
    WNI CSV Structure:
    - Row 1: Group headers (e.g., "Engine", "Fuel Consumption")
    - Row 2: Item headers (e.g., "RPM", "HFO (mt)")
    
    This function combines them into: "Engine_RPM", "Fuel Consumption_HFO (mt)"
    
    Args:
        temp_csv: Path to downloaded CSV file
        
    Returns:
        List of cleaned, combined column headers
    """
    # Read first 2 rows without headers
    hdr = pd.read_csv(temp_csv, nrows=2, header=None)

    # Forward-fill group headers (they span multiple columns)
    groups = hdr.iloc[0].ffill().fillna("")
    items = hdr.iloc[1].fillna("")

    # Combine group and item headers
    combined = []
    for g, i in zip(groups, items):
        g_clean = clean_header(g)
        i_clean = clean_header(i)

        # Only combine if both exist and are different
        if g_clean and i_clean and g_clean.lower() != i_clean.lower():
            combined.append(f"{g_clean}_{i_clean}")
        else:
            combined.append(i_clean or g_clean)

    # Final normalization pass
    def final_normalize(header):
        header = str(header)
        # Remove any remaining newlines / carriage returns
        header = header.replace("\n", " ").replace("\r", " ")
        # Collapse ALL whitespace (this covers embedded newlines too)
        header = re.sub(r"\s+", " ", header)
        return header.strip()

    columns = [final_normalize(c) for c in combined]
    columns = [re.sub(r"\s+", " ", c).strip() for c in columns]

    return columns


# ============================================================
# DATE PICKER AUTOMATION
# ============================================================

def navigate_to_month(page, target_year, target_month):
    """
    Navigates the Logbook+ month picker to the target year/month.
    Returns True if target month reached, False if back button was disabled
    (meaning portal has no data before current displayed month — skip the target).
    """
    MONTH_MAP = {
        "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4,
        "May": 5, "Jun": 6, "Jul": 7, "Aug": 8,
        "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12
    }

    max_clicks = 24
    clicks = 0

    while clicks < max_clicks:
        label = page.locator(r'text=/[A-Z][a-z]{2} \d{4}/').first.inner_text()
        parts = label.strip().split()
        current_month = MONTH_MAP.get(parts[0], 0)
        current_year = int(parts[1])

        if current_year == target_year and current_month == target_month:
            return True  # Reached target

        current_total = current_year * 12 + current_month
        target_total  = target_year  * 12 + target_month

        if target_total < current_total:
            back_btn = page.locator("button:has-text('<'), button[aria-label*='prev'], .month-prev").first
            if not back_btn.is_enabled():
                log.warning(
                    "Back button disabled — portal data starts at %s %d, skipping target %d/%d",
                    parts[0], current_year, target_month, target_year
                )
                return False  # Target month unavailable — tell caller to skip
            back_btn.click()
        else:
            next_btn = page.locator("button:has-text('>'), button[aria-label*='next'], .month-next").first
            try:
                next_btn.wait_for(state="visible", timeout=5000)
                next_btn.click()
            except Exception as e:
                log.warning("Next button click failed: %s — retrying after wait", e)
                page.wait_for_timeout(1000)
                next_btn.click()

        page.wait_for_timeout(800)
        clicks += 1

    if clicks == max_clicks:
        log.warning("Month navigation hit max clicks | target=%d/%d", target_month, target_year)

    return True


# ============================================================
# FLEET STATUS SCRAPER (WNI SSM page)
# ============================================================

def scrape_fleet_status(page, fleet_json_data, api_headers):
    """
    Parses the intercepted Fleet Status JSON data from the WNI portal,
    fetches the current voyage number from Logbook+ for each vessel,
    and saves results to the fleet_status_data table.
    """
    import time as _time
    from ..database import SessionLocal
    from ..models import FleetStatusData

    log.info("[FLEET]    Starting Fleet Status Monitoring scrape via JSON interception...")

    try:
        # ---- Wait for JSON data to be fully captured ----
        # Give it up to 15 seconds to ensure the map API finishes loading
        start_wait = _time.time()
        while _time.time() - start_wait < 15:
            if fleet_json_data["monitoring"] and fleet_json_data["geojson"] and fleet_json_data["fleetlist"] and fleet_json_data["latest_pos"] and fleet_json_data["general_info"]:
                break
            _time.sleep(1)

        if not fleet_json_data["monitoring"]:
            log.error("[FLEET]    Failed to intercept monitoring-list.json!")
            return
            
        monitoring = fleet_json_data.get("monitoring", [])
        
        # Load target vessels
        from ..database import get_scrape_vessels
        import os
        from ..config import config as _cfg
        target_vessels = get_scrape_vessels("wni")
        if not target_vessels:
            vessels_file = os.path.join(_cfg.BASE_DIR, "vessels.txt")
            if os.path.exists(vessels_file):
                with open(vessels_file, "r", encoding="utf-8") as f:
                    target_vessels = [v.strip() for v in f.readlines() if v.strip()]
        
        # --- NEW: Trigger HAR logging by clicking each vessel ---
        log.info("[FLEET]    Clicking each vessel to trigger HAR payload...")
        for m in monitoring:
            name = m.get("vessel_name", "")
            imo = str(m.get("imo", "")).strip()
            if not name: continue
            
            # Click only our vessels
            if target_vessels and name not in target_vessels and imo not in target_vessels:
                continue
                
            try:
                log.info(f"[FLEET]    Clicking {name}...")
                page.get_by_text(name, exact=False).first.click(timeout=5000)
                # Wait for HAR tracking to capture the network request for this vessel
                page.wait_for_timeout(3000)
            except Exception as e:
                log.warning(f"[FLEET]    Could not click vessel {name} in UI: {e}")
        geojson_features = fleet_json_data.get("geojson", {}).get("features", [])
        alerts = fleet_json_data.get("alerts", [])
        fleetlist = fleet_json_data.get("fleetlist", {}).get("data", [])
        latest_pos_features = fleet_json_data.get("latest_pos", {}).get("features", [])
        general_info = fleet_json_data.get("general_info", [])

        # Merge data by IMO or vessel_name
        merged_data = {}
        
        # ── Alert type → DB column mapping ────────────────────────────────────
        ALERT_FIELD_MAP = {
            "Port Alert":       "port_alert",
            "Coastal Storm":    "coastal_storm",
            "Ocean Storm":      "ocean_storm",
            "Tropical Cyclone": "tropical_cyclone",
            "Pos. Diff.":       "pos_diff",
            "Pos Diff":         "pos_diff",
            "Missing Report":   "report_missing",
            "Report Missing":   "report_missing",
        }

        # 1. Base data from monitoring-list.json
        for m in monitoring:
            name = m.get("vessel_name", "")
            if not name: continue

            entry = {
                "vessel_name": name,
                "imo":         str(m.get("imo", "")),
                "callsign":    str(m.get("callsign", "")),
                "status":      m.get("status"),
                "lat":         str(m.get("lat", "")),
                "lon":         str(m.get("lon", "")),
                # speed and heading are NOT in monitoring-list.json —
                # they will be filled in from latest_pos.json (step 5) which
                # is the authoritative live AIS feed for those values.
                "speed":       "",
                "heading":     "",
                "pos_date":    m.get("pos_date") or m.get("ais_time") or m.get("ais_pos_date") or "",
                # Route ID — the byid value used in the GeoJSON route URL
                # monitoring-list.json uses 'object_id' for this internal vessel ID
                "byid":        str(m.get("object_id") or m.get("id") or m.get("vessel_id") or m.get("byid") or ""),
                # prefer dep_port (departure); fall back to pre_port (previous)
                "last_port":   m.get("dep_port") or m.get("pre_port"),
                "etd":         m.get("etd"),
                # prefer explicit next_port; fall back to arr_port
                "next_port":   m.get("next_port") or m.get("arr_port"),
                "eta":         m.get("eta"),
                "rta":         m.get("rta"),
                "rep_time":    m.get("rep_time"),
                "rep_type":    m.get("rep_type"),
                "service":     m.get("service"),
                "section":     m.get("section"),
                # Default all alert columns to None
                "port_alert":       None,
                "coastal_storm":    None,
                "ocean_storm":      None,
                "tropical_cyclone": None,
                "pos_diff":         None,
                "report_missing":   None,
                "alert_detail":     None,
                "flag_code":        None,
            }

            # Parse alert flags from monitoring-list 'alerts' array directly
            mon_alerts = m.get("alerts") or []
            if isinstance(mon_alerts, list):
                for ma in mon_alerts:
                    alert_name = ma if isinstance(ma, str) else (
                        ma.get("alert_type") or ma.get("type") or ""
                    )
                    alert_name = str(alert_name).strip()
                    field = ALERT_FIELD_MAP.get(alert_name)
                    if field:
                        entry[field] = alert_name

            merged_data[name] = entry
            
            # WNI alerts in monitoring array are sometimes stored in 'alerts' array
            # Let's parse active alerts if present
            # But the explicit alert dots are better mapped manually from geojson or alert-list

        # 2. GeoJSON data (speed, heading, pos_date, alerts, section)
        for f in geojson_features:
            props = f.get("properties", {})
            name = props.get("vessel_name", "")
            if name not in merged_data:
                # Also try matching by imo_no
                imo_no = str(props.get("imo_no", "")).strip()
                if imo_no:
                    for k, v in merged_data.items():
                        if str(v.get("imo", "")).strip() == imo_no:
                            name = k
                            break
            if name in merged_data:
                # Only use GeoJSON speed/heading/pos_date as FALLBACK —
                # monitoring-list.json AIS values take priority (more accurate/live)
                if not merged_data[name].get("speed"):
                    merged_data[name]["speed"]   = str(props.get("speed", ""))
                if not merged_data[name].get("heading"):
                    merged_data[name]["heading"] = str(props.get("heading", ""))
                if not merged_data[name].get("pos_date"):
                    merged_data[name]["pos_date"] = props.get("time", "")
                # section from geojson (overrides monitoring if present)
                if props.get("section"):
                    merged_data[name]["section"] = props.get("section")
                # total_distance
                if props.get("total_distance") is not None:
                    merged_data[name]["total_distance"] = str(props.get("total_distance"))
                
                # Map specific WNI alerts from the geojson 'alert' array
                geojson_alerts = props.get("alert") or []
                for ga in (geojson_alerts if isinstance(geojson_alerts, list) else []):
                    ga_str = str(ga).strip()
                    field = ALERT_FIELD_MAP.get(ga_str)
                    if field:
                        merged_data[name][field] = ga_str
                # Legacy exact-string checks for safety
                if "Port Alert" in geojson_alerts:
                    merged_data[name]["port_alert"] = "Port Alert"
                if "Coastal Storm" in geojson_alerts:
                    merged_data[name]["coastal_storm"] = "Coastal Storm"
                if "Ocean Storm" in geojson_alerts:
                    merged_data[name]["ocean_storm"] = "Ocean Storm"
                if "Tropical Cyclone" in geojson_alerts:
                    merged_data[name]["tropical_cyclone"] = "Tropical Cyclone"
                if "Pos. Diff." in geojson_alerts or "Pos Diff" in geojson_alerts:
                    merged_data[name]["pos_diff"] = "Pos. Diff."
                if "Missing Report" in geojson_alerts or "Report Missing" in geojson_alerts:
                    merged_data[name]["report_missing"] = "Missing Report"

        # 3. Fleetlist data (DWT, Ship Type, wnishipnum)
        name_lookup = {k.strip().upper(): k for k in merged_data.keys()}
        for fl in fleetlist:
            name_raw = fl.get("ship_name", "")
            name_clean = name_raw.strip().upper()
            imo_raw = str(fl.get("imo_num") or "").strip()

            # Match by normalized name first, fallback to IMO
            target_name = name_lookup.get(name_clean)
            if not target_name and imo_raw:
                for k, v in merged_data.items():
                    if str(v.get("imo", "")).strip() == imo_raw:
                        target_name = k
                        break
            
            if target_name:
                merged_data[target_name]["dwt"]        = str(fl.get("dwt", ""))
                merged_data[target_name]["ship_type"]  = fl.get("ship_type", "")
                merged_data[target_name]["wnishipnum"] = str(fl.get("wnishipnum", ""))
                
        # 4. Alert-list.json — authoritative source for alert columns + detail text
        for al in alerts:
            name = al.get("vessel_name", "")
            if name in merged_data:
                atype   = str(al.get("alert_type",   "") or "").strip()
                adetail = str(al.get("alert_detail", "") or "").strip()

                # Set the individual alert column (this is the most reliable source)
                field = ALERT_FIELD_MAP.get(atype)
                if field:
                    merged_data[name][field] = atype

                # Build/append combined alert_detail string
                current_detail = merged_data[name].get("alert_detail") or ""
                new_str = f"{atype}: {adetail}" if adetail else atype
                merged_data[name]["alert_detail"] = (
                    current_detail + " | " + new_str if current_detail else new_str
                )

        # 5. Live AIS Data (latest_pos.json) — authoritative source for position,
        #    speed, heading and timestamp. Must override whatever monitoring-list
        #    had, including valid zero values (stopped ship or heading due north).
        for f in latest_pos_features:
            props = f.get("properties", {})
            imo = str(props.get("imo", "")).strip()
            if imo:
                # Find matching vessel by IMO
                v_name = None
                for k, v in merged_data.items():
                    if str(v.get("imo", "")).strip() == imo:
                        v_name = k
                        break
                if v_name:
                    # Update lat/lon with the live AIS position
                    ais_lat = props.get("lat")
                    ais_lon = props.get("lon")
                    if ais_lat is not None:
                        merged_data[v_name]["lat"] = str(ais_lat)
                    if ais_lon is not None:
                        merged_data[v_name]["lon"] = str(ais_lon)
                    # Use 'is not None' so valid zero readings (speed=0, heading=0)
                    # are preserved — truthiness check would silently drop them
                    ais_speed   = props.get("aisspeed")
                    ais_heading = props.get("aisheading")
                    if ais_speed is not None:
                        merged_data[v_name]["speed"]   = str(ais_speed)
                    if ais_heading is not None:
                        merged_data[v_name]["heading"] = str(ais_heading)
                    merged_data[v_name]["pos_date"] = str(props.get("aistimestamp", ""))
                    
        # 6. General Info (general-info.json)
        for g in general_info:
            imo = str(g.get("imo_number", "")).strip()
            if imo:
                v_name = None
                for k, v in merged_data.items():
                    if str(v.get("imo", "")).strip() == imo:
                        v_name = k
                        break
                if v_name:
                    b_date = str(g.get("data_of_build", "")).strip()
                    if len(b_date) == 6: b_date = f"{b_date[:4]}/{b_date[4:]}"
                    elif len(b_date) == 4: b_date = f"{b_date}/01"
                    
                    merged_data[v_name]["build_date"] = b_date
                    merged_data[v_name]["flag_code"] = str(g.get("flag_code", ""))
                    merged_data[v_name]["length"] = str(g.get("length_overall_oa", ""))
                    merged_data[v_name]["breadth"] = str(g.get("breadth", ""))
                    merged_data[v_name]["depth"] = str(g.get("depth", ""))
                    merged_data[v_name]["draft"] = str(g.get("draught", ""))
                    merged_data[v_name]["gross_tonnage"] = str(g.get("gross_tonnage", ""))
                    merged_data[v_name]["engine_builder"] = str(g.get("main_engine_builder", ""))
                    merged_data[v_name]["power_mcr"] = str(g.get("power_bhpihpshpmax", ""))
                    merged_data[v_name]["rpm_mcr"] = str(g.get("rpm_at_mcr", ""))
                    merged_data[v_name]["teu"] = str(g.get("teu", ""))
                    merged_data[v_name]["email"] = str(g.get("email", ""))
                    merged_data[v_name]["fax"] = str(g.get("fax", ""))
                    merged_data[v_name]["phone"] = str(g.get("phone", ""))

        wni_data = list(merged_data.values())
        
        # --- Filter out vessels that are not in our DB ---
        db_session = SessionLocal()
        try:
            from ..models import Vessel
            vessels_in_db = db_session.query(Vessel).all()
            valid_imos = set()
            for v in vessels_in_db:
                if v.imo_number:
                    valid_imos.add(str(v.imo_number).strip())
            
            # Keep if imo matches OR if we don't have imo tracking yet for some reason
            # It's safest to match strictly on IMO
            wni_data = [d for d in wni_data if d.get("imo") in valid_imos]
        except Exception as e:
            log.warning(f"[FLEET]    Failed to filter by DB vessels: {e}")
        finally:
            db_session.close()
        # --------------------------------------------------
        
        log.info(f"[FLEET]    Intercepted {len(wni_data)} vessels from JSON APIs (after DB filter).")

        # ---- Fetch Route GeoJSONs ----
        try:
            from ..config import config as _cfg
            import json as _json
            tracks_dir = str(_cfg.ROOT_DIR / "data" / "wni" / "tracks")
            os.makedirs(tracks_dir, exist_ok=True)
            
            log.info(f"[FLEET]    api_headers being used for route fetch: {api_headers}")
            
            for entry in wni_data:
                wnishipnum = entry.get("wnishipnum")
                byid       = entry.get("byid")         # preferred: from monitoring-list.json
                imo        = entry.get("imo")
                log.info(f"[FLEET]    Vessel IMO={imo}, wnishipnum={wnishipnum}, byid={byid}")
                # Use byid if available (correct route URL), fall back to wnishipnum
                route_id = byid or wnishipnum
                if route_id and imo:
                    route_url = f"https://vp.weathernews.com/customer/IPA/ssm/data/vessel/byid/{route_id}.geojson"
                    try:
                        # Pass captured headers from the session to our fetch call
                        route_data = page.evaluate(f'''async (hdrs) => {{
                            const resp = await fetch("{route_url}", {{ 
                                headers: hdrs, 
                                credentials: 'include' 
                            }});
                            if (!resp.ok) return {{ error: resp.status, text: resp.statusText }};
                            return await resp.json();
                        }}''', api_headers)
                        if route_data and not route_data.get("error"):
                            route_path = os.path.join(tracks_dir, f"{imo}_route.geojson")
                            with open(route_path, "w", encoding="utf-8") as _f:
                                _json.dump(route_data, _f)
                            log.info(f"[FLEET]    Saved route for IMO={imo} using id={route_id}")
                        else:
                            log.warning(f"[FLEET]    Route fetch failed for IMO={imo} id={route_id}: {route_data}")
                    except Exception as e:
                        log.warning(f"[FLEET]    Exception in route fetch for {imo}: {e}")
        except Exception as e:
            log.warning(f"[FLEET]    Failed during route fetch loop: {e}")

        # ---- Post-process: rename byid_*.geojson files to {imo}_route.geojson ----
        # The auto-interceptor saves routes as byid_XXXXX_route.geojson without IMO.
        # Map both wnishipnum and byid to IMO to ensure rename works.
        try:
            id_to_imo = {}
            for entry in wni_data:
                imo = entry.get("imo")
                if imo:
                    if entry.get("byid"): id_to_imo[str(entry["byid"])] = imo
                    if entry.get("wnishipnum"): id_to_imo[str(entry["wnishipnum"])] = imo

            for fname in os.listdir(tracks_dir):
                if fname.startswith("byid_") and fname.endswith("_route.geojson"):
                    byid_val = fname.replace("byid_", "").replace("_route.geojson", "")
                    imo = id_to_imo.get(byid_val)
                    if imo:
                        old_path = os.path.join(tracks_dir, fname)
                        new_path = os.path.join(tracks_dir, f"{imo}_route.geojson")
                        os.replace(old_path, new_path)
                        log.info(f"[FLEET]    Renamed {fname} → {imo}_route.geojson")
        except Exception as e:
            log.warning(f"[FLEET]    byid rename step failed: {e}")
            
        # ---- Navigate to Logbook+ to get voyage numbers ----
        # Open hamburger sidebar
        for sel in ["div.bg-dark-sidemenu-background", "a:has(div.bg-dark-sidemenu-background)"]:
            loc = page.locator(sel).first
            try:
                if loc.count() > 0 and loc.is_visible():
                    loc.click()
                    break
            except Exception:
                continue
        page.wait_for_timeout(1000)

        page.get_by_text("Logbook+", exact=True).click()
        page.wait_for_load_state("networkidle")

        # Close sidebar drawer if visible
        try:
            backdrop = page.locator("div.w-screen.h-screen.fixed.z-40.inset-0").first
            if backdrop.count() > 0 and backdrop.is_visible():
                backdrop.click(force=True, timeout=10000)
        except Exception:
            pass
        page.wait_for_timeout(500)

        # JS snippet to read voyage number from first table row
        VOYAGE_JS = """
        () => {
            const header = document.querySelector('#gplogbk-table-header-voyage_num');
            if (!header) return null;
            const headerRow = header.closest('tr');
            if (!headerRow) return null;
            const colIndex = Array.prototype.indexOf.call(headerRow.children, header);
            if (colIndex === -1) return null;
            const table = header.closest('table');
            if (!table) return null;
            const tbody = table.querySelector('tbody');
            if (!tbody) return null;
            const firstRow = tbody.querySelector('tr');
            if (!firstRow) return null;
            const cell = firstRow.children[colIndex];
            if (!cell) return null;
            return cell.textContent.trim();
        }
        """

        previous_voyage = None
        for entry in wni_data:
            callsign = (entry.get("callsign") or "").strip().upper()
            vessel   = entry.get("vessel_name", "")

            if not callsign:
                entry["voyage_number"] = None
                continue

            target_text = f"{vessel.strip().upper()} / {callsign}"
            try:
                v_input = page.locator("input.simple-typeahead-input")
                v_input.wait_for(state="visible", timeout=10000)
                v_input.click(force=True)
                v_input.fill("")
                v_input.type(vessel, delay=50)
                page.wait_for_timeout(800)

                list_container = page.locator(".simple-typeahead-list")
                try:
                    list_container.wait_for(state="visible", timeout=5000)
                except Exception:
                    entry["voyage_number"] = None
                    continue

                options = list_container.locator("> *")
                matched = None
                for _ in range(10):
                    for i in range(options.count()):
                        opt = options.nth(i)
                        try:
                            txt = opt.evaluate("el => el.textContent.trim()").upper()
                        except Exception:
                            continue
                        if txt == target_text:
                            matched = opt
                            break
                    if matched:
                        break
                    page.mouse.wheel(0, 200)
                    page.wait_for_timeout(300)

                if not matched:
                    entry["voyage_number"] = None
                    continue

                matched.click()
                page.wait_for_timeout(1500)

                # Read voyage number, retrying until it differs from previous
                start = _time.time()
                voyage_num = None
                last_val   = None
                stable     = 0
                while (_time.time() - start) * 1000 < 25000:
                    snap = None
                    try:
                        snap = page.evaluate(VOYAGE_JS)
                    except Exception:
                        pass
                    if snap:
                        if previous_voyage and snap == previous_voyage:
                            stable = 0
                            page.wait_for_timeout(300)
                            continue
                        if snap == last_val:
                            stable += 1
                            if stable >= 3:
                                voyage_num = snap
                                break
                        else:
                            last_val = snap
                            stable   = 1
                    page.wait_for_timeout(300)

                entry["voyage_number"] = voyage_num
                if voyage_num:
                    previous_voyage = voyage_num

            except Exception as ve:
                log.warning(f"[FLEET]    Voyage lookup failed for {vessel}: {ve}")
                entry["voyage_number"] = None

        # ---- Save all entries to fleet_status_data table ----
        db = SessionLocal()
        try:
            for entry in wni_data:
                record = FleetStatusData(
                    vessel_name      = entry.get("vessel_name"),
                    imo              = entry.get("imo"),
                    callsign         = entry.get("callsign"),
                    ship_type        = entry.get("ship_type"),
                    lat              = entry.get("lat"),
                    lon              = entry.get("lon"),
                    speed            = entry.get("speed"),
                    heading          = entry.get("heading"),
                    status           = entry.get("status"),
                    pos_date         = entry.get("pos_date"),
                    last_port        = entry.get("last_port"),
                    etd              = entry.get("etd"),
                    next_port        = entry.get("next_port"),
                    eta              = entry.get("eta"),
                    rta              = entry.get("rta"),
                    voyage_number    = entry.get("voyage_number"),
                    port_alert       = entry.get("port_alert"),
                    coastal_storm    = entry.get("coastal_storm"),
                    ocean_storm      = entry.get("ocean_storm"),
                    tropical_cyclone = entry.get("tropical_cyclone"),
                    pos_diff         = entry.get("pos_diff"),
                    report_missing   = entry.get("report_missing"),
                    dwt              = entry.get("dwt"),
                    rep_time         = entry.get("rep_time"),
                    rep_type         = entry.get("rep_type"),
                    service          = entry.get("service"),
                    alert_detail     = entry.get("alert_detail"),
                    flag_code        = entry.get("flag_code"),
                    build_date       = entry.get("build_date"),
                    length           = entry.get("length"),
                    breadth          = entry.get("breadth"),
                    depth            = entry.get("depth"),
                    draft            = entry.get("draft"),
                    gross_tonnage    = entry.get("gross_tonnage"),
                    engine_builder   = entry.get("engine_builder"),
                    power_mcr        = entry.get("power_mcr"),
                    rpm_mcr          = entry.get("rpm_mcr"),
                    teu              = entry.get("teu"),
                    email            = entry.get("email"),
                    fax              = entry.get("fax"),
                    phone            = entry.get("phone"),
                )
                db.add(record)
            db.commit()
            log.info(f"[FLEET]    Saved {len(wni_data)} fleet status records to database.")
        except Exception as db_err:
            db.rollback()
            log.error(f"[FLEET]    DB save failed: {db_err}")
        finally:
            db.close()

        # ---- Save CSV (same folder as WNI Logbook+ downloads) ----
        try:
            import csv
            from datetime import datetime as _dt
            from ..config import config as _cfg
            csv_dir = os.getenv("WNI_OUTPUT_DIR", str(_cfg.ROOT_DIR / "data" / "wni"))
            os.makedirs(csv_dir, exist_ok=True)
            today_str = _dt.utcnow().strftime("%Y-%m-%d")
            csv_path  = os.path.join(csv_dir, f"fleet_status_{today_str}.csv")

            CSV_COLUMNS = [
                "vessel_name", "imo", "callsign", "ship_type", "voyage_number",
                "speed", "heading", "status", "pos_date",
                "last_port", "etd", "next_port", "eta", "rta",
                "lat", "lon",
                "port_alert", "coastal_storm", "ocean_storm",
                "tropical_cyclone", "pos_diff", "report_missing",
                "dwt", "rep_time", "rep_type", "service", "alert_detail", "flag_code"
            ]

            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(wni_data)

            log.info(f"[FLEET]    CSV saved → {csv_path}")
        except Exception as csv_err:
            log.warning(f"[FLEET]    CSV export failed: {csv_err}")

    except Exception as e:
        log.error(f"[FLEET]    Fleet Status scrape failed: {e}")




# ============================================================
# MAIN PIPELINE EXECUTION
# ============================================================

def run():
    init_db()
    log.info("Starting WNI pipeline")

    # Define dynamic date range
    # HISTORICAL_START_DATE = datetime(2026, 3, 31)
    # HISTORICAL_START_DATE = datetime(2025, 8, 1)
    # HISTORICAL_START_DATE = datetime(2025, 12, 1)
    HISTORICAL_START_DATE = datetime(2026, 6, 1)
    end_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)   # today (dynamic)

    # Build list of (month_start, month_end) tuples from Aug 1 → today
    month_ranges = []
    cursor = HISTORICAL_START_DATE
    while cursor <= end_date:
        month_start = cursor
        month_end = (cursor + relativedelta(months=1)) - relativedelta(days=1)
        if month_end > end_date:
            month_end = end_date
        month_ranges.append((month_start, month_end))
        cursor += relativedelta(months=1)

    # Output directory
    # --- LOCAL (original hardcoded path — uncomment to use) ---
    # EXCEL_OUTPUT_DIR = r"C:\Users\Seenu Maheshwaran\Documents\OZELLAR\WNI"
    # --- VM / CROSS-PLATFORM (env var, default <project_root>/data/wni) ---
    from ..config import config as _cfg
    EXCEL_OUTPUT_DIR = os.getenv("WNI_OUTPUT_DIR", str(_cfg.ROOT_DIR / "data" / "wni"))
    os.makedirs(EXCEL_OUTPUT_DIR, exist_ok=True)

    # Counters for summary report
    vessels_processed = 0
    vessels_failed = 0

    # ============================================================
    # BROWSER INITIALIZATION
    # ============================================================
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--start-maximized"])
        from ..config import config as _cfg
        har_path = str(_cfg.ROOT_DIR / "data" / "wni" / "fleet_status.har")
        os.makedirs(os.path.dirname(har_path), exist_ok=True)
        context = browser.new_context(
            no_viewport=True, 
            accept_downloads=True,
            record_har_path=har_path
        )
        page = context.new_page()

        # Set timeouts for stability
        page.set_default_timeout(30000)
        page.set_default_navigation_timeout(60000)

        # ============================================================
        # WNI PORTAL LOGIN
        # ============================================================
        
        log.info("Opening Weathernews login page")

        # --- JSON Interception Setup ---
        fleet_json_data = {
            "monitoring": [],
            "geojson": {},
            "alerts": [],
            "fleetlist": {},
            "latest_pos": {},
            "general_info": []
        }
        
        # Store captured headers to reuse for our manual fetch
        api_headers = {}
        
        def handle_wni_request(request):
            headers = request.headers
            if "authorization" in headers:
                api_headers["authorization"] = headers["authorization"]
            if "x-api-key" in headers:
                api_headers["x-api-key"] = headers["x-api-key"]
            if "x-wni-token" in headers:
                api_headers["x-wni-token"] = headers["x-wni-token"]

        page.on("request", handle_wni_request)
        
        def handle_wni_response(response):
            url = response.url
            if "latest_pos.json" in url:
                try: fleet_json_data["latest_pos"] = response.json()
                except: pass
            if "general-info.json" in url:
                try: fleet_json_data["general_info"] = response.json()
                except: pass
            if "/api/v2/fleetlist/find" in url:
                try: fleet_json_data["fleetlist"] = response.json()
                except: pass
            elif "/monitoring-list.json" in url:
                try: fleet_json_data["monitoring"] = response.json()
                except: pass
            elif "/alert-list.json" in url:
                try: fleet_json_data["alerts"] = response.json()
                except: pass
            elif "bytm/" in url and ".geojson" in url:
                try: fleet_json_data["geojson"] = response.json()
                except: pass
            elif "/ssm/data/vessel/byid/" in url and url.endswith(".geojson"):
                # Intercept live route GeoJSON fired when the map loads each vessel
                # URL pattern: /customer/IPA/ssm/data/vessel/byid/{id}.geojson
                try:
                    import re as _re
                    from ..config import config as _cfg
                    route_data = response.json()
                    if not isinstance(route_data, dict) or "features" not in route_data:
                        log.debug(f"[FLEET]    Skipping invalid/error route response from {url}: {route_data}")
                        return
                    features = route_data.get("features", [])
                    imo = None
                    for feat in features:
                        props = feat.get("properties", {})
                        imo = str(props.get("imo_no") or props.get("imo") or "").strip()
                        if imo:
                            break
                    if imo:
                        tracks_dir = str(_cfg.ROOT_DIR / "data" / "wni" / "tracks")
                        os.makedirs(tracks_dir, exist_ok=True)
                        route_path = os.path.join(tracks_dir, f"{imo}_route.geojson")
                        with open(route_path, "w", encoding="utf-8") as _f:
                            import json as _json
                            _json.dump(route_data, _f)
                        log.info(f"[FLEET]    Auto-intercepted route for IMO={imo} from {url}")
                    else:
                        # Save by byid as fallback
                        m = _re.search(r'/byid/(\d+)\.geojson', url)
                        if m:
                            byid = m.group(1)
                            tracks_dir = str(_cfg.ROOT_DIR / "data" / "wni" / "tracks")
                            os.makedirs(tracks_dir, exist_ok=True)
                            route_path = os.path.join(tracks_dir, f"byid_{byid}_route.geojson")
                            with open(route_path, "w", encoding="utf-8") as _f:
                                import json as _json
                                _json.dump(route_data, _f)
                            log.info(f"[FLEET]    Auto-intercepted route by byid={byid} (no IMO found)")
                except Exception as _te:
                    log.debug(f"[FLEET]    byid route intercept failed for {url}: {_te}")
            elif "track" in url.lower() and response.headers.get("content-type", "").startswith("application/"):
                # Per-vessel track GeoJSON — save immediately when intercepted
                try:
                    from ..config import config as _cfg
                    track_data = response.json()
                    features = track_data.get("features", [])
                    imo = None
                    # Try to extract IMO from feature properties
                    for feat in features:
                        props = feat.get("properties", {})
                        imo = str(props.get("imo_no") or props.get("imo") or "").strip()
                        if imo:
                            break
                    # Fall back: try to parse IMO from URL (e.g. .../9832925/track...)
                    if not imo:
                        import re as _re
                        m = _re.search(r'/(\d{7,9})/', url)
                        if m:
                            imo = m.group(1)
                    if imo:
                        tracks_dir = str(_cfg.ROOT_DIR / "data" / "wni" / "tracks")
                        os.makedirs(tracks_dir, exist_ok=True)
                        track_path = os.path.join(tracks_dir, f"{imo}.geojson")
                        with open(track_path, "w", encoding="utf-8") as _f:
                            import json as _json
                            _json.dump(track_data, _f)
                        log.info(f"[FLEET]    Saved track → {track_path}")
                except Exception as _te:
                    log.debug(f"[FLEET]    Track intercept failed for {url}: {_te}")
                
        page.on("response", handle_wni_response)
        # -------------------------------
        
        page.goto(config.WNI_LOGIN_URL)

        # Click login button
        page.locator("#login_buttom").click()
        
        # Enter username
        page.get_by_role("textbox", name="Username or email address").fill(
            config.WNI_USERNAME
        )
        page.get_by_role("button", name="Continue").click()
        
        # Enter password
        page.get_by_role("textbox", name="Password").fill(
            config.WNI_PASSWORD
        )
        page.get_by_role("button", name="Continue").click()
        
        # Wait for login to complete
        page.wait_for_load_state("networkidle")
        log.info("Login successful")

        # ── Fleet Status Monitoring scrape (SSM map page) ──────────────────
        # Runs once per day right after login. Navigates to the SSM map,
        # scrapes vessel positions + port data, then fetches voyage numbers
        # from Logbook+. Saves to fleet_status_data table.
        scrape_fleet_status(page, fleet_json_data, api_headers)
        log.info("[FLEET]    Fleet Status scrape complete.")
        
        # --- USER REQUEST: Run ONLY fleet status scrape ---
        log.info("Stopping pipeline early to only run Fleet Status scrape.")
        return

        # Navigate back to Logbook+ for the normal CSV downloads
        page.wait_for_selector("a", timeout=20000)
        page.evaluate("""
            [...document.querySelectorAll('a')]
              .find(a => a.innerText.includes('Logbook+'))
              .click()
        """)
        page.wait_for_load_state("networkidle")
        log.info("Logbook+ re-opened for CSV downloads")

        # ============================================================
        # NAVIGATE TO LOGBOOK+
        # ============================================================
        
        page.wait_for_selector("a", timeout=20000)
        
        # Find and click Logbook+ link using JavaScript
        page.evaluate("""
            [...document.querySelectorAll('a')]
              .find(a => a.innerText.includes('Logbook+'))
              .click()
        """)
        page.wait_for_load_state("networkidle")
        log.info("Logbook+ opened")

        # ============================================================
        # LOAD VESSEL LIST
        # ============================================================
        
        # Vessel list is DB-driven (vessels table, wni_enabled flag) — no
        # more vessels.txt. Falls back to the file only if the DB returns none.
        from ..database import get_scrape_vessels
        vessels = get_scrape_vessels("wni")
        if not vessels:
            vessels_file = os.path.join(config.BASE_DIR, "vessels.txt")
            with open(vessels_file, "r", encoding="utf-8") as f:
                vessels = [v.strip() for v in f.readlines() if v.strip()]
        log.info("Loaded %d WNI vessels from DB: %s", len(vessels), ", ".join(vessels))

        # ============================================================
        # --- DATE ITERATION LOGIC (Vessel-first, Month by Month) ---
        # ============================================================

        # Outer loop: one vessel at a time
        for vessel in vessels:
            # Extract clean vessel name (before any "/" character)
            v_name_clean = vessel.split("/")[0].strip()
            safe_vessel = v_name_clean.replace(" ", "_")

            # Excel filename: VESSEL_NAME_WNI.xlsx (all months combined)
            excel_filename = f"{safe_vessel}_WNI.xlsx"
            excel_path = os.path.join(EXCEL_OUTPUT_DIR, excel_filename)

            log.info("Processing vessel | name=%s | output=%s", v_name_clean, excel_filename)

            # Collect monthly DataFrames for this vessel
            all_months_df = []

            # Inner loop: month by month for this vessel
            for current_start_date, _ in month_ranges:
                month_label = current_start_date.strftime("%b %Y")

                try:
                    # ---- VESSEL SELECTION ----
                    vessel_box = page.get_by_role("textbox", name="Vessel Name")
                    vessel_box.fill("")  # Clear existing selection
                    vessel_box.type(vessel)  # Type vessel name
                    page.wait_for_timeout(1000)  # Wait for dropdown
                    page.locator(f"text='{vessel}'").first.click()  # Select from dropdown

                    # ---- NAVIGATE TO CORRECT MONTH ----
                    # Returns False if portal has no data for this month (back button disabled)
                    if not navigate_to_month(page, current_start_date.year, current_start_date.month):
                        log.info("Skipping unavailable month | vessel=%s | month=%s", v_name_clean, month_label)
                        continue
                    page.wait_for_load_state("networkidle")

                    # ---- DOWNLOAD CSV ----
                    with page.expect_download() as d:
                        page.get_by_role(
                            "button",
                            name="Download Table as CSV"
                        ).click()

                    download = d.value

                    # Save the download as a temporary CSV first
                    temp_csv = os.path.join(EXCEL_OUTPUT_DIR, f"{safe_vessel}_temp.csv")
                    download.save_as(temp_csv)

                    # Parse the CSV data
                    headers = get_wni_headers(temp_csv)
                    df = pd.read_csv(temp_csv, skiprows=2, names=headers)

                    # Clean up the temporary CSV
                    if os.path.exists(temp_csv):
                        os.remove(temp_csv)

                    # Skip if no data
                    if df.empty:
                        log.info("No data | vessel=%s | month=%s", v_name_clean, month_label)
                        continue

                    # Log what date range the portal actually returned
                    if "Date" in df.columns:
                        dates = pd.to_datetime(df["Date"], errors="coerce").dropna()
                        if not dates.empty:
                            log.info(
                                "Downloaded | vessel=%s | month=%s | rows=%d | date_range=%s to %s",
                                v_name_clean, month_label, len(df),
                                dates.min().date(), dates.max().date()
                            )

                    all_months_df.append(df)

                except Exception:
                    log.exception(
                        "Vessel processing failed | vessel=%s | month=%s | stage=processing",
                        v_name_clean,
                        month_label
                    )

            # ---- COMBINE ALL MONTHS & WRITE EXCEL ----
            if all_months_df:
                combined_df = pd.concat(all_months_df, ignore_index=True)

                # Deduplicate only on Date + Event Type (not all columns)
                dedup_cols = [c for c in ["Date", "Event Type"] if c in combined_df.columns]
                if dedup_cols:
                    combined_df.drop_duplicates(subset=dedup_cols, keep="first", inplace=True)
                else:
                    combined_df.drop_duplicates(inplace=True)

                # SAVE AS EXCEL (.xlsx) PERMANENTLY
                combined_df.to_excel(excel_path, index=False)
                log.info("Excel saved | vessel=%s | file=%s | rows=%d", v_name_clean, excel_filename, len(combined_df))

                # ---- DATA QUALITY CHECK ----
                csv_dup_count = combined_df.duplicated().sum()
                if csv_dup_count > 0:
                    log.warning(
                        "CSV-level duplicates | vessel=%s | count=%d",
                        v_name_clean,
                        csv_dup_count
                    )

                # Clean NaN values for database
                db_df = combined_df.replace({pd.NA: None, np.nan: None})

                # ---- SAVE TO DATABASE ----
                total_rows = len(db_df)
                inserted = 0
                duplicates = 0
                failed = 0

                # Process each row
                for _, row in db_df.iterrows():
                    result = save_to_db(
                        v_name_clean,
                        row.to_dict(),
                        excel_filename  # Pass the Excel filename for auditing
                    )

                    # Track results
                    if result == "success":
                        inserted += 1
                    elif result == "duplicate":
                        duplicates += 1
                    else:
                        failed += 1

                # Log summary for this vessel
                log.info(
                    "DB write summary | vessel=%s | total=%d | inserted=%d | duplicates=%d | failed=%d",
                    v_name_clean,
                    total_rows,
                    inserted,
                    duplicates,
                    failed
                )

                vessels_processed += 1

            else:
                log.warning("No data found across all months | vessel=%s", v_name_clean)
                vessels_failed += 1

        # Close browser
        browser.close()

    # ============================================================
    # PIPELINE COMPLETION
    # ============================================================
    
    log.info(
        "Pipeline completed | vessels_processed=%d | vessels_failed=%d",
        vessels_processed,
        vessels_failed
    )



# ============================================================
# DIRECT EXECUTION
# ============================================================

def save_har_to_db():
    from ..config import config as _cfg
    import os
    har_path = str(_cfg.ROOT_DIR / "data" / "wni" / "fleet_status.har")
    if os.path.exists(har_path):
        import json
        from ..database import SessionLocal
        from ..models import RawHarData
        import logging
        log = logging.getLogger(__name__)
        try:
            with open(har_path, 'r', encoding='utf-8') as f:
                har_data = json.load(f)
            db = SessionLocal()
            new_har = RawHarData(
                har_json=har_data,
                file_name="fleet_status.har"
            )
            db.add(new_har)
            db.commit()
            db.close()
            log.info(f"Successfully saved {har_path} to raw_har_data table.")
        except Exception as e:
            log.error(f"Failed to save HAR to DB: {e}")


# ============================================================
# FLEET STATUS ONLY — lightweight scheduled scrape
# ============================================================

def run_fleet_status_only():
    """
    Lightweight scrape that runs on a schedule (e.g. every 30 minutes).
    Logs into WNI, collects fleet status JSON feeds + route GeoJSONs,
    saves to DB, then exits immediately — does NOT run the Logbook+ CSV pipeline.

    Configured via env var:  FLEET_STATUS_INTERVAL_MINUTES  (default: 30)
    """
    import os
    from playwright.sync_api import sync_playwright
    from ..config import config as _cfg
    from ..database import init_db

    _log = logging.getLogger(__name__)
    _log.info("[FLEET_SCHED]  Starting fleet-status-only scrape ...")

    init_db()

    fleet_json_data = {
        "monitoring": [],
        "geojson":    {},
        "alerts":     [],
        "fleetlist":  {},
        "latest_pos": {},
        "general_info": []
    }
    api_headers = {}

    try:
        with sync_playwright() as p:
            # Run silently in the background so it doesn't interrupt the user
            browser = p.chromium.launch(headless=True, args=["--start-maximized"])
            har_path = str(_cfg.ROOT_DIR / "data" / "wni" / "fleet_status.har")
            os.makedirs(os.path.dirname(har_path), exist_ok=True)
            context = browser.new_context(
                no_viewport=True,
                accept_downloads=True,
                record_har_path=har_path
            )
            page = context.new_page()
            page.set_default_timeout(30000)
            page.set_default_navigation_timeout(60000)

            # --- Capture auth headers ---
            def _on_request(request):
                hdrs = request.headers
                if "authorization" in hdrs:
                    api_headers["authorization"] = hdrs["authorization"]
                if "x-api-key" in hdrs:
                    api_headers["x-api-key"] = hdrs["x-api-key"]

            page.on("request", _on_request)
            page.on("response", lambda r: handle_wni_response_standalone(r, fleet_json_data))

            # --- Login ---
            page.goto(config.WNI_LOGIN_URL)
            page.locator("#login_buttom").click()
            page.get_by_role("textbox", name="Username or email address").fill(config.WNI_USERNAME)
            page.get_by_role("button", name="Continue").click()
            page.get_by_role("textbox", name="Password").fill(config.WNI_PASSWORD)
            page.get_by_role("button", name="Continue").click()
            page.wait_for_load_state("networkidle")
            _log.info("[FLEET_SCHED]  Login OK")

            # --- Fleet Status scrape only ---
            scrape_fleet_status(page, fleet_json_data, api_headers)
            _log.info("[FLEET_SCHED]  Fleet status scrape complete.")

            browser.close()

    except Exception as e:
        _log.error(f"[FLEET_SCHED]  Scrape failed: {e}", exc_info=True)


def handle_wni_response_standalone(response, fleet_json_data):
    """
    Reusable response handler used by run_fleet_status_only().
    Mirrors handle_wni_response() inside run() but callable without closure.
    """
    import re as _re
    import json as _json
    import os
    from ..config import config as _cfg

    url = response.url
    try:
        if "latest_pos.json" in url:
            fleet_json_data["latest_pos"] = response.json()
        elif "general-info.json" in url:
            fleet_json_data["general_info"] = response.json()
        elif "/api/v2/fleetlist/find" in url:
            fleet_json_data["fleetlist"] = response.json()
        elif "/monitoring-list.json" in url:
            fleet_json_data["monitoring"] = response.json()
        elif "/alert-list.json" in url:
            fleet_json_data["alerts"] = response.json()
        elif "bytm/" in url and ".geojson" in url:
            fleet_json_data["geojson"] = response.json()
        elif "/ssm/data/vessel/byid/" in url and url.endswith(".geojson"):
            route_data = response.json()
            if not isinstance(route_data, dict) or "features" not in route_data:
                return
            features = route_data.get("features", [])
            imo = None
            for feat in features:
                props = feat.get("properties", {})
                imo = str(props.get("imo_no") or props.get("imo") or "").strip()
                if imo:
                    break
            if imo:
                tracks_dir = str(_cfg.ROOT_DIR / "data" / "wni" / "tracks")
                os.makedirs(tracks_dir, exist_ok=True)
                with open(os.path.join(tracks_dir, f"{imo}_route.geojson"), "w", encoding="utf-8") as _f:
                    _json.dump(route_data, _f)
                log.info(f"[FLEET_SCHED]  Auto-intercepted route IMO={imo}")
            else:
                m = _re.search(r'/byid/(\d+)\.geojson', url)
                if m:
                    byid = m.group(1)
                    tracks_dir = str(_cfg.ROOT_DIR / "data" / "wni" / "tracks")
                    os.makedirs(tracks_dir, exist_ok=True)
                    with open(os.path.join(tracks_dir, f"byid_{byid}_route.geojson"), "w", encoding="utf-8") as _f:
                        _json.dump(route_data, _f)
    except Exception:
        pass


if __name__ == "__main__":
    run()
    save_har_to_db()