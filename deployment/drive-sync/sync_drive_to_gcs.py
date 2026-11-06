#!/usr/bin/env python3
"""
Sync a Google Drive folder (Shared Drive supported) into a GCS bucket, then
optionally trigger a Vertex AI Search / Discovery Engine documents:import.

Team workflow: add/update files in Drive → this job copies to GCS → re-indexes.
No ZIP download required.

Auth for Drive (pick one):
  1. Preferred when Shared Drive blocks external SAs: OAuth as a roboreliance.com
     user who is already a Drive member. Set DRIVE_OAUTH_CLIENT_ID,
     DRIVE_OAUTH_CLIENT_SECRET, DRIVE_OAUTH_REFRESH_TOKEN (see obtain_drive_oauth.py).
  2. ADC / service account — only works if the Shared Drive allows that identity.
"""

from __future__ import annotations

import argparse
import io
import logging
import mimetypes
import os
import sys
from typing import Any, Dict, Iterator, List, Optional, Tuple

import google.auth
import google.auth.transport.requests
import httpx
from google.auth.transport.requests import Request
from google.cloud import storage
from google.oauth2.credentials import Credentials as UserCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("drive-sync")

_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# Native Google Workspace types → export MIME / file extension
_EXPORT_MAP = {
    "application/vnd.google-apps.document": (
        "application/pdf",
        ".pdf",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/pdf",
        ".pdf",
    ),
}

_SKIP_TYPES = {
    "application/vnd.google-apps.folder",
    "application/vnd.google-apps.shortcut",
    "application/vnd.google-apps.form",
    "application/vnd.google-apps.map",
    "application/vnd.google-apps.site",
}


def _drive_credentials():
    """Prefer Workspace-user OAuth (Shared Drive member); else ADC."""
    client_id = os.getenv("DRIVE_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.getenv("DRIVE_OAUTH_CLIENT_SECRET", "").strip()
    refresh_token = os.getenv("DRIVE_OAUTH_REFRESH_TOKEN", "").strip()
    if client_id and client_secret and refresh_token:
        creds = UserCredentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=_DRIVE_SCOPES,
        )
        creds.refresh(Request())
        logger.info("Drive auth: OAuth refresh token (Workspace user)")
        return creds

    credentials, _ = google.auth.default(scopes=_DRIVE_SCOPES)
    logger.info("Drive auth: Application Default Credentials")
    return credentials


def _drive_service():
    return build("drive", "v3", credentials=_drive_credentials(), cache_discovery=False)


def _list_children(service, folder_id: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    page_token = None
    query = f"'{folder_id}' in parents and trashed = false"
    while True:
        resp = (
            service.files()
            .list(
                q=query,
                spaces="drive",
                fields="nextPageToken, files(id, name, mimeType, modifiedTime, md5Checksum, size)",
                pageToken=page_token,
                pageSize=200,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                corpora="allDrives",
            )
            .execute()
        )
        items.extend(resp.get("files") or [])
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return items


def _walk_files(
    service, folder_id: str, prefix: str = ""
) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """Yield (relative_path, file_metadata) for every non-folder under folder_id."""
    for item in _list_children(service, folder_id):
        name = item.get("name") or item["id"]
        mime = item.get("mimeType") or ""
        rel = f"{prefix}{name}" if not prefix else f"{prefix.rstrip('/')}/{name}"
        if mime == "application/vnd.google-apps.folder":
            yield from _walk_files(service, item["id"], rel)
            continue
        if mime in _SKIP_TYPES:
            logger.info("Skipping unsupported type %s (%s)", mime, rel)
            continue
        yield rel, item


def _download_bytes(service, file_meta: Dict[str, Any]) -> Tuple[bytes, str]:
    """Return (content_bytes, object_name_suffix_adjustment)."""
    file_id = file_meta["id"]
    mime = file_meta.get("mimeType") or ""
    name = file_meta.get("name") or file_id

    if mime in _EXPORT_MAP:
        export_mime, ext = _EXPORT_MAP[mime]
        request = service.files().export_media(fileId=file_id, mimeType=export_mime)
        if not name.lower().endswith(ext):
            name = f"{name}{ext}"
    else:
        request = service.files().get_media(fileId=file_id, supportsAllDrives=True)

    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue(), name


def sync_folder_to_gcs(
    *,
    folder_id: str,
    gcs_uri: str,
    dry_run: bool = False,
) -> int:
    if not gcs_uri.startswith("gs://"):
        raise ValueError(f"gcs_uri must start with gs://, got {gcs_uri}")
    path = gcs_uri[len("gs://") :]
    bucket_name, _, prefix = path.partition("/")
    prefix = prefix.rstrip("/")
    if prefix:
        prefix = prefix + "/"

    service = _drive_service()
    gcs = storage.Client()
    bucket = gcs.bucket(bucket_name)

    synced = 0
    for rel_path, meta in _walk_files(service, folder_id):
        try:
            content, final_name = _download_bytes(service, meta)
        except Exception:
            logger.exception("Download failed for %s (%s)", rel_path, meta.get("id"))
            continue

        # Preserve folder structure; replace Google Doc basename with exported name
        parent = rel_path.rsplit("/", 1)[0] if "/" in rel_path else ""
        object_name = f"{prefix}{parent}/{final_name}" if parent else f"{prefix}{final_name}"
        object_name = object_name.lstrip("/")

        content_type = mimetypes.guess_type(final_name)[0] or "application/octet-stream"
        logger.info(
            "%s gs://%s/%s (%d bytes, drive_id=%s)",
            "Would upload" if dry_run else "Uploading",
            bucket_name,
            object_name,
            len(content),
            meta.get("id"),
        )
        if dry_run:
            synced += 1
            continue

        blob = bucket.blob(object_name)
        blob.upload_from_string(content, content_type=content_type)
        # Help Discovery Engine / ops correlate back to Drive
        blob.metadata = {
            "drive_file_id": meta.get("id") or "",
            "drive_modified": meta.get("modifiedTime") or "",
            "source": "drive-sync",
        }
        blob.patch()
        synced += 1

    logger.info("Synced %d file(s) to gs://%s/%s", synced, bucket_name, prefix)
    return synced


def trigger_discovery_import(
    *,
    project_id: str,
    data_store_id: str,
    gcs_uri_glob: str,
) -> Optional[str]:
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    request = google.auth.transport.requests.Request()
    credentials.refresh(request)
    token = credentials.token
    if not token:
        raise RuntimeError("Failed to obtain access token for Discovery Engine import")

    parent = (
        f"projects/{project_id}/locations/global/collections/default_collection/"
        f"dataStores/{data_store_id}/branches/default_branch"
    )
    url = f"https://discoveryengine.googleapis.com/v1/{parent}/documents:import"
    payload = {
        "gcsSource": {
            "inputUris": [gcs_uri_glob],
            "dataSchema": "content",
        },
        "reconciliationMode": "INCREMENTAL",
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "x-goog-user-project": project_id,
    }
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            logger.error("Import failed (%s): %s", resp.status_code, resp.text[:500])
            raise RuntimeError(f"Discovery Engine import failed: {resp.status_code}")
        body = resp.json()
        op = body.get("name")
        logger.info("Started Discovery Engine import operation: %s", op)
        return op


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--folder-id",
        default=os.getenv("DRIVE_FOLDER_ID", "1quTosmucf3hb3fjrWCSW2keudcd7Yj5I"),
        help="Google Drive folder ID to sync",
    )
    parser.add_argument(
        "--gcs-uri",
        default=os.getenv("GCS_URI", "gs://robo-reliance-ops-sop-chef"),
        help="Destination GCS URI (bucket or bucket/prefix)",
    )
    parser.add_argument(
        "--project-id",
        default=os.getenv("GOOGLE_CLOUD_PROJECT")
        or os.getenv("GCP_PROJECT")
        or "robo-reliance-ops",
    )
    parser.add_argument(
        "--data-store-id",
        default=os.getenv("DATA_STORE_ID", "sop-chef"),
        help="Discovery Engine data store to re-import into",
    )
    parser.add_argument(
        "--skip-import",
        action="store_true",
        help="Only sync to GCS; do not call documents:import",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    count = sync_folder_to_gcs(
        folder_id=args.folder_id,
        gcs_uri=args.gcs_uri,
        dry_run=args.dry_run,
    )
    if args.dry_run or args.skip_import:
        return 0 if count >= 0 else 1

    glob_uri = args.gcs_uri.rstrip("/") + "/**"
    trigger_discovery_import(
        project_id=args.project_id,
        data_store_id=args.data_store_id,
        gcs_uri_glob=glob_uri,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
