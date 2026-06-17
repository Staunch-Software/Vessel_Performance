import os
import urllib.parse
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class Config:
    ROOT_DIR = Path(__file__).resolve().parent.parent
    LOG_DIR  = ROOT_DIR / "logs"
    os.makedirs(LOG_DIR, exist_ok=True)

    PIPELINE_LOG = LOG_DIR / "wni_pipeline.log"
    WEEKLY_LOG   = LOG_DIR / "weekly_report.log"

    # =========================================================
    # DIRECTORY SETTINGS
    # =========================================================

    BASE_DIR = Path(__file__).resolve().parent

    # Where WNI CSV files are temporarily stored
    DOWNLOAD_DIR = ROOT_DIR / "data" / "wni" / "historical"
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    # Historical MariApps data
    # --- LOCAL (original hardcoded path — uncomment to use on your machine) ---
    # MARIAPPS_DOWNLOAD_DIR = Path(
    #     r"C:\Users\Seenu Maheshwaran\Documents\OZELLAR\Mariapps"
    # )
    # --- VM / CROSS-PLATFORM (env var, default <project_root>/data/mariapps) ---
    MARIAPPS_DOWNLOAD_DIR = Path(
        os.getenv("MARIAPPS_DOWNLOAD_DIR", str(ROOT_DIR / "data" / "mariapps"))
    )
    os.makedirs(MARIAPPS_DOWNLOAD_DIR, exist_ok=True)

    # =========================================================
    # DATABASE
    # =========================================================

    DB_USER    = os.getenv("DB_USER")
    _raw_pass  = os.getenv("DB_PASSWORD")
    DB_PASS    = urllib.parse.quote_plus(_raw_pass) if _raw_pass else ""
    DB_HOST    = os.getenv("DB_HOST", "localhost")
    DB_PORT    = os.getenv("DB_PORT", "5432")
    DB_NAME    = os.getenv("DB_NAME")
    DATABASE_URL = (
        f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )

    # =========================================================
    # WNI
    # =========================================================

    WNI_USERNAME  = os.getenv("WN_USERNAME")
    WNI_PASSWORD  = os.getenv("WN_PASSWORD")
    WNI_LOGIN_URL = os.getenv("WNI_LOGIN_URL")

    # =========================================================
    # MARIAPPS
    # =========================================================

    MARIAPPS_URL       = os.getenv("MARIAPPS_URL")
    MARIAPPS_AUTH_JSON = BASE_DIR / "mariapps_pipeline" / "auth.json"

    # =========================================================
    # EYEGAUGE  (Sea Vision  —  tb-rest-client SDK, Option 2)
    # =========================================================

    # Base URL for the Sea Vision platform
    EYEGAUGE_BASE_URL = os.getenv("EYEGAUGE_BASE_URL", "https://sea.vision")

    # Login credentials  (set these in your .env file)
    EYEGAUGE_USERNAME = os.getenv("EYEGAUGE_USERNAME")
    EYEGAUGE_PASSWORD = os.getenv("EYEGAUGE_PASSWORD")

    # Vessel IMO number — used by the SDK to locate the correct ASSET
    # Change this if you switch vessels; the pipeline reads it from here.
    EYEGAUGE_VESSEL_IMO = os.getenv("EYEGAUGE_VESSEL_IMO", "9811048")


# ---------------------------------------------------------------------------
# Optional: explicit list of telemetry keys to fetch.
# Set to None (or leave as-is) to fetch ALL available keys automatically.
# ---------------------------------------------------------------------------
EYEGAUGE_TELEMETRY_KEYS = None   # None = fetch everything

# If you want to restrict to specific keys, uncomment and edit:
# EYEGAUGE_TELEMETRY_KEYS = [
#     # Navigation / Vessel Data
#     "ACTUAL SPEED", "LOG", "SOG", "lat", "lon",
#     "windspeedKmph", "winddirDegree", "beaufort",
#     "currentSpeed", "currentDirection", "waveHeight", "swellHeight",
#     # Engine / Performance Data
#     "me-rpm", "me-load", "me-power", "me-fuel-index",
#     "me-scav-air", "turbo-rpm", "consumption-me-mtpd",
#     "me-fuel-temp", "me-cal-value", "me-rt1",
#     # Generators / Boiler Data
#     "total-kw", "1-kw", "2-kw", "3-kw",
#     "consumption-dg-mtpd", "dg-fuel-temp",
#     "consumption-boiler-mtpd", "boiler-fuel-flow", "boiler-fuel-temp",
# ]

config = Config()