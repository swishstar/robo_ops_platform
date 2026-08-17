"""
Webhook caller verification for Slack and Google Chat.

Slack: HMAC-SHA256 of `v0:{timestamp}:{raw_body}` using SLACK_SIGNING_SECRET.
Google Chat: Bearer JWT from chat@system.gserviceaccount.com (project-number or
HTTP-endpoint audience) or the Workspace Add-ons Chat service agent.

See:
  https://api.slack.com/authentication/verifying-requests-from-slack
  https://developers.google.com/workspace/chat/verify-requests-from-chat
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from typing import Optional

from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)

CHAT_ISSUER = "chat@system.gserviceaccount.com"
CHAT_CERTS_URL = (
    "https://www.googleapis.com/service_accounts/v1/metadata/x509/"
    + CHAT_ISSUER
)

# Slack rejects requests older than ~5 minutes to limit replay.
SLACK_MAX_SKEW_SECONDS = 60 * 5


def _is_local_development() -> bool:
    return os.getenv("ENVIRONMENT", "development") == "development"


def _fail_closed_webhooks() -> bool:
    """When true, missing webhook secrets reject rather than skip verification."""
    explicit = os.getenv("REQUIRE_WEBHOOK_VERIFICATION", "").strip().lower()
    if explicit in {"1", "true", "yes"}:
        return True
    if explicit in {"0", "false", "no"}:
        return False
    return not _is_local_development()


def _allowed_chat_emails() -> set[str]:
    """
    Accept classic Chat issuer and Workspace Add-ons Chat service agent.

    Newer Chat API Configuration UIs show Service Account Email
    service-PROJECT_NUMBER@gcp-sa-gsuiteaddons.iam.gserviceaccount.com and
    omit the Authentication Audience radio (audience is the HTTP endpoint URL).
    """
    emails = {CHAT_ISSUER}
    project_number = os.getenv("GOOGLE_CLOUD_PROJECT_NUMBER", "").strip()
    if project_number:
        emails.add(
            f"service-{project_number}@gcp-sa-gsuiteaddons.iam.gserviceaccount.com"
        )
    extra = os.getenv("GOOGLE_CHAT_ALLOWED_EMAILS", "").strip()
    for part in extra.split(","):
        email = part.strip()
        if email:
            emails.add(email)
    return emails


def verify_slack_request(request: Request, raw_body: bytes) -> None:
    """
    Validate X-Slack-Signature / X-Slack-Request-Timestamp.

    No-ops when SLACK_SIGNING_SECRET is unset in local development.
    """
    secret = os.getenv("SLACK_SIGNING_SECRET", "").strip()
    if not secret:
        if _fail_closed_webhooks():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Slack signing secret is not configured.",
            )
        logger.warning("SLACK_SIGNING_SECRET unset; skipping Slack signature check")
        return

    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")
    if not timestamp or not signature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Slack signature headers.",
        )

    try:
        ts = int(timestamp)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Slack request timestamp.",
        ) from exc

    if abs(time.time() - ts) > SLACK_MAX_SKEW_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Slack request timestamp too old.",
        )

    basestring = b"v0:" + timestamp.encode("utf-8") + b":" + raw_body
    digest = hmac.new(
        secret.encode("utf-8"),
        basestring,
        hashlib.sha256,
    ).hexdigest()
    expected = f"v0={digest}"

    if not hmac.compare_digest(expected, signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Slack signature.",
        )


def _bearer_token(authorization: Optional[str]) -> str:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header.",
        )
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header.",
        )
    return parts[1].strip()


def verify_google_chat_request(authorization: Optional[str]) -> None:
    """
    Validate Google Chat bearer JWT.

    Audience resolution:
      1. GOOGLE_CHAT_AUDIENCE — HTTP endpoint URL (OIDC ID token; current Console default)
      2. GOOGLE_CLOUD_PROJECT_NUMBER — project-number self-signed JWT mode (legacy)
    """
    http_audience = os.getenv("GOOGLE_CHAT_AUDIENCE", "").strip()
    project_audience = os.getenv("GOOGLE_CLOUD_PROJECT_NUMBER", "").strip()

    if not http_audience and not project_audience:
        if _fail_closed_webhooks():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Google Chat audience is not configured.",
            )
        logger.warning(
            "GOOGLE_CHAT_AUDIENCE / GOOGLE_CLOUD_PROJECT_NUMBER unset; "
            "skipping Google Chat JWT check"
        )
        return

    token = _bearer_token(authorization)

    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Chat validation unavailable: google-auth is not installed.",
        ) from exc

    request = google_requests.Request()
    claims = None
    last_error: Optional[Exception] = None
    allowed_emails = _allowed_chat_emails()

    # Prefer OIDC ID-token verification (HTTP endpoint audience).
    # GOOGLE_CHAT_AUDIENCE may be a comma-separated list of accepted audiences.
    audiences = [a.strip() for a in http_audience.split(",") if a.strip()]
    for audience in audiences:
        try:
            claims = id_token.verify_oauth2_token(token, request, audience)
            email = claims.get("email")
            if email not in allowed_emails:
                raise ValueError(
                    f"email claim {email!r} is not an allowed Chat service account"
                )
            break
        except Exception as exc:
            last_error = exc
            claims = None

    # Fall back to project-number JWT signed by the classic Chat SA certs.
    if claims is None and project_audience:
        try:
            claims = id_token.verify_token(
                token,
                request,
                audience=project_audience,
                certs_url=CHAT_CERTS_URL,
            )
            if claims.get("iss") != CHAT_ISSUER:
                raise ValueError("iss claim is not chat@system.gserviceaccount.com")
        except Exception as exc:
            last_error = exc
            claims = None

    if claims is None:
        logger.warning("Google Chat JWT validation failed: %s", last_error)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Google Chat bearer token.",
        )
