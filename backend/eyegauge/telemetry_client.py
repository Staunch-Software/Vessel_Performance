import pandas as pd
import logging
from datetime import datetime, timezone
from tb_rest_client.rest_client_pe import RestClientPE
from tb_rest_client.rest import ApiException
from tb_rest_client.models.models_ce import EntityId

logger = logging.getLogger(__name__)


class EyegaugeTelemetryClient:

    ALLOWED_DEVICE_TYPES = ["engine", "flowmeters", "generators"]

    # 1 hour in milliseconds
    INTERVAL_MS = 60 * 60 * 1000
    # 1 day per chunk = 24 intervals (well within API limit)
    CHUNK_DAYS  = 1

    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.client: RestClientPE | None = None

    # ── Public ────────────────────────────────────────────────────────────────

    def login(self):
        self.client = RestClientPE(base_url=self.base_url)
        self.client.login(username=self.username, password=self.password)
        logger.info("Authentication successful.")

    def logout(self):
        if self.client:
            try:
                self.client.logout()
            except Exception:
                pass
            self.client = None

    def get_all_data(
        self,
        imo: str,
        start_dt: datetime,
        end_dt: datetime,
        max_data_points: int = 100_000,
        wanted_keys: list | None = None,
    ) -> pd.DataFrame:

        if self.client is None:
            raise RuntimeError("Call login() before get_all_data().")

        start_ts = self._dt_to_ts(start_dt)
        end_ts   = self._dt_to_ts(end_dt)

        # Find vessel ASSET
        asset_id, asset_name = self._get_asset_by_imo(imo)
        if asset_id is None:
            raise ValueError(f"No vessel found for IMO {imo}.")
        logger.info(f"Vessel found: {asset_name}")

        # Fetch ASSET (navigation/weather)
        logger.info("Fetching navigation data (ASSET) ...")
        asset_df = self._fetch_entity_telemetry(
            "ASSET", asset_id, start_ts, end_ts, max_data_points, wanted_keys
        )
        logger.info(f"Navigation data fetched — {len(asset_df)} hourly rows.")

        # Fetch DEVICEs
        device_list = self._get_all_devices(asset_id)
        combined_df = asset_df

        for dev in device_list:
            logger.info(f"Fetching {dev['name']} data ...")
            dev_df = self._fetch_entity_telemetry(
                "DEVICE", dev["device_id"],
                start_ts, end_ts, max_data_points, wanted_keys,
            )
            logger.info(f"{dev['name'].capitalize()} data fetched — {len(dev_df)} hourly rows.")
            combined_df = pd.concat([combined_df, dev_df], axis=1)

        # Resample to exact 1-hour buckets and forward-fill small gaps
        if not combined_df.empty:
            combined_df = combined_df.resample("1h").mean()

        logger.info(
            f"All data combined — {len(combined_df)} hourly rows x "
            f"{len(combined_df.columns)} sensor columns."
        )
        return combined_df

    # ── Private ───────────────────────────────────────────────────────────────

    def _dt_to_ts(self, dt: datetime) -> int:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)

    def _get_asset_by_imo(self, imo: str) -> tuple[str | None, str | None]:
        page, page_size = 0, 20
        while True:
            try:
                result = self.client.get_user_assets(
                    page_size=page_size, page=page
                ).to_dict()
            except ApiException:
                return None, None

            for asset in result.get("data", []):
                asset_id   = asset["id"]["id"]
                asset_name = asset.get("name", "Unknown")
                configured_imo = self._get_asset_attribute(asset_id, "imo")
                if configured_imo and str(configured_imo).strip() == str(imo).strip():
                    return asset_id, asset_name

            if result.get("has_next", False):
                page += 1
            else:
                break
        return None, None

    def _get_asset_attribute(self, asset_id: str, attribute_name: str) -> str | None:
        try:
            attrs = self.client.get_attributes(EntityId(asset_id, "ASSET"))
            for attr in attrs:
                if str(attr.get("key")) == attribute_name:
                    return str(attr.get("value"))
        except Exception:
            pass
        return None

    def get_voyage_number(self, asset_id: str) -> str | None:
        """
        Fetch the current voyage number from ASSET attributes.
        Tries multiple possible key names used by Eyegauge / ThingsBoard.
        """
        possible_keys = [
            "voyageNum", "voyage_num", "voyageNumber",
            "voyage_number", "VoyageNo", "voyage_no", "VoyageNum",
        ]
        for key in possible_keys:
            val = self._get_asset_attribute(asset_id, key)
            if val and val.strip() and val.strip().lower() not in ("none", "null", "nan"):
                logger.info(f"Voyage number found via key '{key}': {val}")
                return val.strip()
        logger.warning("Voyage number not found in ASSET attributes. Will be NULL.")
        return None

    def get_all_asset_attribute_keys(self, asset_id: str) -> list:
        """
        Debug helper — prints ALL attribute keys on the ASSET.
        Run this once to find the exact voyage number key name.
        """
        try:
            attrs = self.client.get_attributes(EntityId(asset_id, "ASSET"))
            keys = [attr.get("key") for attr in attrs]
            logger.info(f"All ASSET attribute keys: {keys}")
            return keys
        except Exception as e:
            logger.warning(f"Could not fetch ASSET attributes: {e}")
            return []

    def _get_all_devices(self, asset_id: str) -> list[dict]:
        devices = []
        try:
            relations = self.client.find_by_from(
                from_id=EntityId(asset_id, "ASSET"), relation_type="Contains"
            )
            if not relations:
                return []
            for rel in relations:
                device_id = rel.to_dict()["to"]["id"]
                try:
                    device_info = self.client.get_device_by_id(
                        EntityId(device_id, "DEVICE")
                    ).to_dict()
                    device_type = device_info.get("type", "").lower()
                    if device_type in self.ALLOWED_DEVICE_TYPES:
                        devices.append({"name": device_type, "device_id": device_id})
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Failed to retrieve devices: {e}")
        return devices

    def _get_entity_keys(
        self, entity_type: str, entity_id: str, wanted_keys: list | None
    ) -> str:
        try:
            keys = self.client.get_timeseries_keys_v1(EntityId(entity_id, entity_type))
            if wanted_keys:
                keys = [k for k in keys if k in wanted_keys]
            return ",".join(keys)
        except Exception:
            return ""

    def _fetch_entity_telemetry(
        self,
        entity_type: str,
        entity_id: str,
        start_ts: int,
        end_ts: int,
        limit: int,
        wanted_keys: list | None,
    ) -> pd.DataFrame:
        """
        Fetch raw data chunked by 1 day per API call (= 24 x 1-hour intervals).
        After collecting all raw points, resample to exact 1-hour buckets.
        """
        keys_str = self._get_entity_keys(entity_type, entity_id, wanted_keys)
        if not keys_str:
            return pd.DataFrame()

        chunk_ms    = self.CHUNK_DAYS * 24 * 60 * 60 * 1000   # 1 day in ms
        total_days  = max(1, int((end_ts - start_ts) / chunk_ms) + 1)
        all_frames  = []
        chunk_start = start_ts
        day_num     = 0

        while chunk_start < end_ts:
            chunk_end  = min(chunk_start + chunk_ms, end_ts)
            day_num   += 1
            try:
                raw = self.client.get_timeseries(
                    EntityId(entity_id, entity_type),
                    start_ts=chunk_start,
                    end_ts=chunk_end,
                    keys=keys_str,
                    limit=limit,
                    agg="NONE",              # raw data — resample to 1h after
                    interval=None,
                )
                df_chunk = self._build_dataframe(raw)
                if not df_chunk.empty:
                    all_frames.append(df_chunk)
            except ApiException as e:
                body = getattr(e, "body", b"")
                if isinstance(body, bytes):
                    body = body.decode()
                logger.debug(f"Day {day_num}/{total_days} skipped: {body[:80]}")
            chunk_start = chunk_end

        if not all_frames:
            return pd.DataFrame()

        # Combine all raw points then resample to 1-hour mean
        df_raw = pd.concat(all_frames)
        df_raw = df_raw[~df_raw.index.duplicated(keep="first")]
        df_raw.sort_index(inplace=True)

        # Resample: 1 row per hour, average all readings within that hour
        df_hourly = df_raw.resample("1h").mean()
        return df_hourly

    def _build_dataframe(self, raw: dict) -> pd.DataFrame:
        rows = {}
        for key, records in raw.items():
            if not isinstance(records, list):
                continue
            for item in records:
                ts  = pd.to_datetime(item["ts"], unit="ms", utc=True)
                val = item.get("value", None)
                # Convert to float; skip empty strings and non-numeric values
                if val is None or str(val).strip() == "":
                    val = None
                else:
                    try:
                        val = float(val)
                    except (ValueError, TypeError):
                        val = None
                if ts not in rows:
                    rows[ts] = {}
                rows[ts][key] = val
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame.from_dict(rows, orient="index")
        df.index.name = None
        return df