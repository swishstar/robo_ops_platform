#!/usr/bin/env python3
"""
One-time: authorize a roboreliance.com Workspace user (who can already open the
Chef Shared Drive) and print a refresh token for Secret Manager.

Prereqs:
  1. GCP Console → APIs & Services → Credentials → Create OAuth client ID
     Application type: Desktop app
     Name: e.g. inner-loop-drive-sync
  2. OAuth consent screen: Internal (Workspace) is fine
  3. Run this script as a Drive member (browser login)

Then store the printed values in Secret Manager (see deploy-drive-sync-job.sh).
"""

from __future__ import annotations

import argparse
import json
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--client-secrets",
        required=True,
        help="Path to OAuth Desktop client JSON downloaded from GCP Console",
    )
    args = parser.parse_args()

    flow = InstalledAppFlow.from_client_secrets_file(args.client_secrets, SCOPES)
    creds = flow.run_local_server(port=0)
    if not creds.refresh_token:
        print(
            "No refresh_token returned. Revoke prior grants at "
            "https://myaccount.google.com/permissions and re-run with prompt=consent.",
            file=sys.stderr,
        )
        return 1

    with open(args.client_secrets, encoding="utf-8") as f:
        raw = json.load(f)
    installed = raw.get("installed") or raw.get("web") or {}
    client_id = installed.get("client_id", "")
    client_secret = installed.get("client_secret", "")

    print("\n=== Store these in Secret Manager / env ===\n")
    print(f"DRIVE_OAUTH_CLIENT_ID={client_id}")
    print(f"DRIVE_OAUTH_CLIENT_SECRET={client_secret}")
    print(f"DRIVE_OAUTH_REFRESH_TOKEN={creds.refresh_token}")
    print(
        "\nSuggested secrets:\n"
        "  gcloud secrets create inner-loop-drive-oauth-client-id --data-file=-\n"
        "  gcloud secrets create inner-loop-drive-oauth-client-secret --data-file=-\n"
        "  gcloud secrets create inner-loop-drive-oauth-refresh-token --data-file=-\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
