import os
import json
import logging
from pathlib import Path
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv
load_dotenv()

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

WARTSILA_USERNAME = os.getenv("WARTSILA_USERNAME", "techdevops@ozellar.com")
WARTSILA_PASSWORD = os.getenv("WARTSILA_PASSWORD", "G$788329274973ad")

# Wartsila internal vesselId mapping
AMNS_VESSELS = {
    "6900-195": "9961609",  # AMNS POLAR
    "6900-016": "9942768",  # AMNSI MAXIMUS
    "6169-999": "9942770",  # AMNSI STALLION
}

# Static general vessel info sourced from public maritime databases
VESSEL_GENERAL_INFO = {
    "9961609": {  # AMNS POLAR
        "callsign": "VTWT",
        "flag_code": "IN",
        "ship_type": "BULK CARRIER",
        "build_date": "2012",
        "length": "149.5",
        "breadth": "23.7",
        "dwt": "19560",
        "gross_tonnage": "13579",
    },
    "9942768": {  # AMNSI MAXIMUS
        "callsign": "VTOC",
        "flag_code": "IN",
        "ship_type": "BULK CARRIER",
        "build_date": "2012",
        "length": "229",
        "breadth": "32",
        "dwt": "81666",
        "gross_tonnage": "44310",
    },
    "9942770": {  # AMNSI STALLION
        "callsign": "VTNZ",
        "flag_code": "IN",
        "ship_type": "BULK CARRIER",
        "build_date": "2012",
        "length": "229",
        "breadth": "32",
        "dwt": "81666",
        "gross_tonnage": "44310",
    },
}

def wartsila_to_geojson(data: dict, imo: str, wp_data: dict = None) -> dict:
    """
    Converts Wartsila location3 API response (raw lat/lon/time arrays)
    into a standard GeoJSON FeatureCollection.
    Feature 1: Historical track (breadcrumbs from location3)
    Feature 2: Planned route from waypoints (if provided)
    This is the format the frontend /track API endpoint expects.
    """
    lons = data.get("lon", [])
    lats = data.get("lat", [])
    times = data.get("time", [])
    sogs = data.get("sog", [])
    
    coordinates = [[lons[i], lats[i]] for i in range(min(len(lons), len(lats)))]
    
    features = [
        {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": coordinates
            },
            "properties": {
                "imo_no": imo,
                "source": "wartsila",
                "routetype": "actual",   # WNI-compatible: renders as white dashed historical track
                "times": times,
                "sogs": sogs,
                "point_count": len(coordinates)
            }
        }
    ]
    
    # Add planned route from waypoints if available
    if wp_data:
        route_pts = wp_data.get("routePoints", {})
        if isinstance(route_pts, dict):
            xs = route_pts.get("xs", [])
            ys = route_pts.get("ys", [])
            if xs and ys:
                import math
                # Convert Web Mercator (EPSG:3857) meters to WGS84 lon/lat
                planned_coords = []
                for x, y in zip(xs, ys):
                    lon_deg = x * 180.0 / 20037508.342789244
                    lat_deg = math.degrees(math.atan(math.sinh(y * math.pi / 20037508.342789244)))
                    planned_coords.append([round(lon_deg, 5), round(lat_deg, 5)])
                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": planned_coords
                    },
                    "properties": {
                        "imo_no": imo,
                        "source": "wartsila",
                        "routetype": "future",  # WNI-compatible: renders as yellow dashed future route
                        "point_count": len(planned_coords)
                    }
                })
    
    return {
        "type": "FeatureCollection",
        "features": features
    }


# Persistent browser session directory - stores cookies/localStorage across runs
SESSION_DIR = Path(__file__).resolve().parent.parent.parent / ".wartsila_session"


def fetch_wartsila_routes():
    """
    Scrapes Wartsila FOS for the route GeoJSON of AMNS vessels.
    Saves the GeoJSONs directly into the WNI tracks directory so the frontend can read them.
    Uses a persistent browser context so login session is preserved between runs.
    """
    log.info("[WARTSILA] Starting route scrape for AMNS vessels...")
    
    tracks_dir_path = Path(os.getenv("ROOT_DIR", str(Path(__file__).resolve().parent.parent.parent))) / "data" / "wni" / "tracks"
    try:
        from ..config import config as _cfg
        tracks_dir_path = _cfg.ROOT_DIR / "data" / "wni" / "tracks"
    except Exception:
        pass
    tracks_dir = str(tracks_dir_path)
    os.makedirs(tracks_dir, exist_ok=True)
    
    SESSION_DIR.mkdir(exist_ok=True)
    
    with sync_playwright() as p:
        # Use persistent context so session cookies survive between scheduled runs
        context = p.chromium.launch_persistent_context(
            str(SESSION_DIR),
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        # With persistent context, there's already an open page — reuse it
        pages = context.pages
        page = pages[0] if pages else context.new_page()
        
        xsrf_token = ""
        
        def handle_request(request):
            nonlocal xsrf_token
            if not xsrf_token and "x-xsrf-token" in request.headers:
                xsrf_token = request.headers["x-xsrf-token"]
                
        page.on("request", handle_request)
        
        try:
            try:
                log.info("[WARTSILA] Navigating to Wartsila FOS...")
                page.goto("https://fos.wartsila.com/monitoring", wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                log.info(f"[WARTSILA] Navigation interrupted (likely a redirect), continuing... Details: {e}")
            page.wait_for_timeout(5000)
            
            # Login flow
            if page.locator("input[name='loginfmt']").count() > 0:
                log.info("[WARTSILA] Filling Microsoft SSO...")
                page.fill("input[name='loginfmt']", WARTSILA_USERNAME)
                page.wait_for_timeout(2000)
                # Use JS click to bypass Microsoft SSO overlay/lightbox issues
                page.wait_for_selector("#idSIButton9", state="visible", timeout=10000)
                page.evaluate("document.querySelector('#idSIButton9').click()")
                page.wait_for_timeout(3000)
                
                try:
                    if page.locator("text=Use your password instead").count() > 0:
                        page.get_by_text("Use your password instead").click(timeout=5000)
                        page.wait_for_timeout(2000)
                except Exception:
                    try:
                        if page.locator("#idA_PWD_SwitchToPassword").count() > 0:
                            page.locator("#idA_PWD_SwitchToPassword").click(timeout=5000)
                            page.wait_for_timeout(2000)
                    except Exception:
                        pass
                
                page.wait_for_selector("input[name='passwd']", state="visible", timeout=10000)
                page.fill("input[name='passwd']", WARTSILA_PASSWORD)
                # JS click to bypass overlay on password submit button
                page.evaluate("(function(){ var btn = document.querySelector('input[type=submit]'); if(btn) btn.click(); })()")
                page.wait_for_timeout(5000)
                
                if page.locator("input[value='Yes']").count() > 0:
                    page.evaluate("(function(){ var btn = document.querySelector('input[value=Yes]'); if(btn) btn.click(); })()")
                    page.wait_for_timeout(3000)
                
                # Wait for redirect to fos.wartsila.com (poll startswith to avoid matching redirect_uri)
                log.info("[WARTSILA] Waiting for redirect to fos.wartsila.com...")
                for _ in range(30):
                    page.wait_for_timeout(2000)
                    if page.url.startswith("https://fos.wartsila.com"):
                        log.info(f"[WARTSILA] Redirected to: {page.url}")
                        break
                page.wait_for_timeout(5000)
                log.info(f"[WARTSILA] At: {page.url}")
            else:
                log.info("[WARTSILA] Session reused — already logged in.")
                try:
                    page.reload(wait_until="domcontentloaded")
                except Exception:
                    try:
                        page.goto("https://fos.wartsila.com/monitoring", wait_until="domcontentloaded", timeout=30000)
                    except Exception as e:
                        log.info(f"[WARTSILA] Navigation interrupted (likely a redirect), continuing... Details: {e}")
                page.wait_for_timeout(3000)
                
            log.info("[WARTSILA] Waiting for page load and token capture...")
            page.wait_for_timeout(10000)
            
            if not xsrf_token:
                # Read XSRF token directly from cookie - works even when already logged in
                log.info("[WARTSILA] No token from headers, reading from cookies...")
                try:
                    cookies = context.cookies()
                    for c in cookies:
                        if "XSRF" in c.get("name", "").upper() or "CSRF" in c.get("name", "").upper():
                            xsrf_token = c["value"]
                            log.info(f"[WARTSILA] Got XSRF from cookie '{c['name']}'")
                            break
                    if not xsrf_token:
                        log.info(f"[WARTSILA] Cookies: {[c['name'] for c in cookies]}")
                except Exception as ce:
                    log.warning(f"[WARTSILA] Cookie read failed: {ce}")
            
            if not xsrf_token:
                log.error("[WARTSILA] Failed to capture XSRF token!")
                context.close()
                return False
                
            log.info(f"[WARTSILA] Captured X-XSRF-TOKEN. Fetching routes...")
            
            headers = {
                "Content-Type": "application/json", 
                "Accept": "application/json",
                "X-XSRF-TOKEN": xsrf_token
            }
            
            # Fetch all latest2 data once
            import time
            now_ms = int(time.time() * 1000)
            latest2_url = f"https://fos.wartsila.com/x/fleet2-service/v1/data/latest2?time={now_ms}"
            latest2_resp = page.request.get(latest2_url, headers=headers)
            all_latest2 = []
            if latest2_resp.status == 200:
                all_latest2 = latest2_resp.json()
                
            # Fetch for each AMNS vessel
            url = "https://fos.wartsila.com/x/fleet2-service/v1/data/location3"
            for vessel_id, imo in AMNS_VESSELS.items():
                payload = {
                    "vesselId": vessel_id,
                    "simplify": True
                }
                
                response = page.request.post(
                    url,
                    data=payload,
                    headers=headers
                )
                
                if response.status == 200:
                    data = response.json()
                    
                    # Fetch waypoints FIRST so planned route can be included in geojson
                    wp_url = f"https://fos.wartsila.com/x/fleet2-service-routes/v1/data/waypoints?vessel={vessel_id}&time={now_ms}"
                    wp_resp = page.request.get(wp_url, headers=headers)
                    wp_data = wp_resp.json() if wp_resp.status == 200 else {}
                    
                    # Build geojson with both historical track + planned route
                    geojson_data = wartsila_to_geojson(data, imo, wp_data)
                    route_path = os.path.join(tracks_dir, f"{imo}_route.geojson")
                    with open(route_path, "w", encoding="utf-8") as f:
                        json.dump(geojson_data, f)
                    log.info(f"[WARTSILA] Successfully saved route for IMO={imo} (ID={vessel_id})")
                    
                    # Find matching latest2
                    l2_data = {}
                    for entry in all_latest2:
                        if isinstance(entry, dict) and entry.get("vesselId") == vessel_id:
                            l2_data = entry
                            break
                    
                    # Save current position to FleetStatusData for map display
                    _save_fleet_status(data, vessel_id, imo, l2_data, wp_data)
                else:
                    log.error(f"[WARTSILA] Failed to fetch route for {vessel_id}. Status: {response.status}")
            
        except Exception as e:
            log.error(f"[WARTSILA] Scrape exception: {e}")
            context.close()
            return False
            
        context.close()
        return True


# Vessel name mapping (Wartsila vesselId -> display name)
VESSEL_NAMES = {
    "6900-195": "AMNS POLAR",
    "6900-016": "AMNSI MAXIMUS",
    "6169-999": "AMNSI STALLION",
}


def _save_fleet_status(route_data: dict, vessel_id: str, imo: str, l2_data: dict, wp_data: dict):
    """
    Saves the current position of a Wärtsilä-tracked vessel into the
    FleetStatusData table so it appears alongside WNI vessels on the map.
    Uses the most recent lat/lon/sog/time from the route data.
    """
    try:
        from ..database import SessionLocal
        from ..models import FleetStatusData

        lons = route_data.get("lon", [])
        lats = route_data.get("lat", [])
        sogs = route_data.get("sog", [])
        times = route_data.get("time", [])
        cogs = route_data.get("cog", [])

        if not lons or not lats:
            log.warning(f"[WARTSILA] No position data for IMO={imo}")
            return

        # Most recent position = last element
        latest_lon = lons[-1]
        latest_lat = lats[-1]
        latest_sog = sogs[-1] if sogs else None
        latest_time = times[-1] if times else None
        latest_cog = cogs[-1] if cogs else None

        vessel_name = VESSEL_NAMES.get(vessel_id, f"WARTSILA-{vessel_id}")

        # Convert time to readable string (match WNI JS Date format)
        pos_date_str = None
        if latest_time:
            import datetime
            dt = datetime.datetime.fromtimestamp(latest_time / 1000.0, datetime.timezone.utc)
            pos_date_str = dt.strftime("%a %b %d %Y %H:%M:%S GMT+0000 (Coordinated Universal Time)")

        # Extract voyage details from waypoints data
        departure = wp_data.get("departurePort", {}).get("name") if isinstance(wp_data.get("departurePort"), dict) else None
        destination = wp_data.get("destinationPort", {}).get("name") if isinstance(wp_data.get("destinationPort"), dict) else None
        route_name = wp_data.get("name")
        
        eta_str = None
        import datetime
        # Extract ETA at destination from routePoints.etas (last entry = final destination ETA)
        route_pts = wp_data.get("routePoints", {})
        if isinstance(route_pts, dict):
            etas_list = route_pts.get("etas", [])
            if etas_list:
                last_eta_ms = etas_list[-1]
                dt_eta = datetime.datetime.fromtimestamp(last_eta_ms / 1000.0, datetime.timezone.utc)
                eta_str = dt_eta.strftime("%Y-%m-%dT%H:%M:%SZ")
        
        if not eta_str:
            # fallback: check individual waypoint eta fields
            wps = wp_data.get("wayPoints", [])
            if wps:
                eta_val = wps[-1].get("eta") or wps[-1].get("arrivalTime")
                if eta_val:
                    dt_eta = datetime.datetime.fromtimestamp(eta_val / 1000.0, datetime.timezone.utc)
                    eta_str = dt_eta.strftime("%Y-%m-%dT%H:%M:%SZ")

        departure = departure.upper() if departure else None
        destination = destination.upper() if destination else None
        route_name = route_name.upper() if route_name else None

        # Prefer extracting ports from route name to match user expectations
        # e.g. "VOY 067 L VIZAG TO HAZIRA" -> departure="VIZAG", destination="HAZIRA"
        if route_name and " TO " in route_name:
            parts = route_name.split(" TO ")
            dest_parsed = parts[-1].strip() if parts else None
            
            before_to = parts[0].strip()
            # Strip voyage number tokens from the front
            tokens = before_to.split()
            port_tokens = []
            skipping_voy = True
            for tok in tokens:
                if skipping_voy:
                    if tok in ("VOY", "VYG"):
                        continue
                    if any(char.isdigit() for char in tok):
                        continue  # e.g. "067", "060L"
                    if len(tok) <= 2:
                        continue  # e.g. "L", "B"
                skipping_voy = False
                port_tokens.append(tok)
            dep_parsed = " ".join(port_tokens) if port_tokens else None
            
            departure = dep_parsed if dep_parsed else departure
            destination = dest_parsed if dest_parsed else destination
        
        # Extract voyage number: everything before " TO " in the route name
        # e.g. "VOY 067 L VIZAG TO HAZIRA" -> "067 L"
        # e.g. "060L HAMBANTOTA TO PARADIP" -> "060L"
        voyage_number = route_name
        if route_name and " TO " in route_name:
            before_to = route_name.split(" TO ")[0].strip()
            # Remove leading "VOY " if present
            if before_to.startswith("VOY "):
                before_to = before_to[4:].strip()
            # Keep only the voyage code part: stop at first all-caps word 4+ chars that is not L/B/E/W/N/S
            tokens = before_to.split()
            voy_tokens = []
            for tok in tokens:
                # A direction/load indicator is 1-2 chars (L, B, H, LD, BL)
                # A voyage number part is digits or 1-2 chars
                # A port name is 4+ all-caps letters
                if len(tok) >= 4 and tok.isalpha() and tok.isupper():
                    break  # hit a port name, stop
                voy_tokens.append(tok)
            if voy_tokens:
                voyage_number = " ".join(voy_tokens)

        # Look up static vessel general info
        gen_info = VESSEL_GENERAL_INFO.get(imo, {})

        db = SessionLocal()
        try:
            record = FleetStatusData(
                vessel_name=vessel_name,
                imo=imo,
                callsign=gen_info.get("callsign"),
                flag_code=gen_info.get("flag_code"),
                lat=str(latest_lat),
                lon=str(latest_lon),
                speed=str(round(float(latest_sog), 1)) if latest_sog is not None else "0",
                heading=str(round(float(latest_cog))) if latest_cog is not None else "0",
                pos_date=pos_date_str,
                status="UNDERWAY" if latest_sog and float(latest_sog) > 0.5 else "ANCHOR",
                ship_type=gen_info.get("ship_type", "BULK CARRIER"),
                last_port=departure,
                next_port=destination,
                eta=eta_str,
                voyage_number=voyage_number,
                build_date=gen_info.get("build_date"),
                length=gen_info.get("length"),
                breadth=gen_info.get("breadth"),
                dwt=gen_info.get("dwt"),
                gross_tonnage=gen_info.get("gross_tonnage"),
            )
            db.add(record)
            db.commit()
            log.info(f"[WARTSILA] Saved FleetStatusData for {vessel_name} ({imo}): lat={latest_lat}, lon={latest_lon}, sog={latest_sog}, eta={eta_str}, ports={departure}->{destination}")
        except Exception as db_err:
            db.rollback()
            log.error(f"[WARTSILA] DB save failed for {imo}: {db_err}")
        finally:
            db.close()

    except Exception as e:
        log.error(f"[WARTSILA] _save_fleet_status failed for {imo}: {e}")


if __name__ == "__main__":
    # Test script directly
    logging.basicConfig(level=logging.INFO)
    fetch_wartsila_routes()
