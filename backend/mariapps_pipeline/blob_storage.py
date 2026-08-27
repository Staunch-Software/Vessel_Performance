# ===========================================================================
# backend/mariapps_pipeline/blob_storage.py
#
# Minimal Azure Blob Storage wrapper for MariApps Bunker Report attachments
# (the actual Bunker Delivery Note PDF scans). Not used by anything else in
# the pipeline — kept scoped to this one feature rather than a shared/generic
# storage module, since nothing else in the project needs blob storage yet.
# ===========================================================================
import logging
from datetime import datetime, timedelta

from azure.storage.blob import BlobServiceClient, ContentSettings, generate_blob_sas, BlobSasPermissions
from ..config import config

log = logging.getLogger(__name__)

_container_client = None


def _get_container_client():
    """Lazily creates (and caches) the container client. Raises a clear error
    if AZURE_STORAGE_CONNECTION_STRING isn't set, rather than failing deep
    inside an upload call with a confusing SDK error."""
    global _container_client
    if _container_client is not None:
        return _container_client

    if not config.AZURE_STORAGE_CONNECTION_STRING:
        raise RuntimeError(
            "AZURE_STORAGE_CONNECTION_STRING is not set in .env — cannot upload "
            "Bunker Report attachments to Azure Blob Storage."
        )

    service = BlobServiceClient.from_connection_string(config.AZURE_STORAGE_CONNECTION_STRING)
    container = service.get_container_client(config.AZURE_STORAGE_CONTAINER)
    try:
        container.create_container()
        log.info(f"[BLOB]     Created container '{config.AZURE_STORAGE_CONTAINER}' (did not exist yet).")
    except Exception:
        pass  # already exists — the common case, not an error

    _container_client = container
    return _container_client


def _safe_path_part(s: str) -> str:
    """Strips characters that are awkward in a blob path (slashes especially,
    since a BDN reference number like 'NORF53-26' can otherwise be fine, but
    some source values do contain '/'). Also collapses any embedded newlines —
    the scraper already extracts just the first line of a multi-line file-name
    cell, but this is a defensive second layer in case a raw value ever slips
    through with one (confirmed real: Azure rejects a newline in a blob path
    as an InvalidUri, not a graceful truncation)."""
    s = (s or "unknown").replace("\r", " ").replace("\n", " ")
    return " ".join(s.split()).strip().replace("/", "-").replace("\\", "-").replace(" ", "_")


def upload_bunker_attachment(vessel_imo: str, bdn_reference_no: str, file_name: str, file_bytes: bytes) -> dict:
    """Uploads one Bunker Delivery Note attachment. Blob path is namespaced by
    vessel IMO so files are easy to browse per-vessel in the Azure portal.
    Returns {"blob_path": <container-relative path>, "blob_url": <full URL>}.
    """
    container = _get_container_client()

    safe_ref  = _safe_path_part(bdn_reference_no)
    safe_name = _safe_path_part(file_name) or "attachment.pdf"
    blob_path = f"{vessel_imo}/{safe_ref}_{safe_name}"

    blob_client = container.get_blob_client(blob_path)
    content_type = "application/pdf" if safe_name.lower().endswith(".pdf") else "application/octet-stream"
    blob_client.upload_blob(
        file_bytes,
        overwrite=True,
        content_settings=ContentSettings(content_type=content_type),
    )

    return {"blob_path": blob_path, "blob_url": blob_client.url}


def get_download_url(blob_path: str, expiry_minutes: int = 60) -> str:
    """Returns a short-lived, read-only SAS URL for one blob — generated fresh
    per request rather than exposing container.get_blob_client(...).url (the
    plain URL) directly to the frontend/API response. These are commercial
    Bunker Delivery Note documents; the container isn't configured for public
    anonymous read, and even if it were, a permanent unauthenticated link is
    the wrong default for this kind of document. Requires the connection
    string to carry an account key (not e.g. a SAS-only connection string) —
    that's what upload_bunker_attachment already assumes too."""
    container = _get_container_client()
    account_key = container.credential.account_key
    sas_token = generate_blob_sas(
        account_name=container.account_name,
        container_name=container.container_name,
        blob_name=blob_path,
        account_key=account_key,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.utcnow() + timedelta(minutes=expiry_minutes),
    )
    blob_client = container.get_blob_client(blob_path)
    return f"{blob_client.url}?{sas_token}"
