"""
Authentication helpers for /api/v1 routes.

Production / Cloud Run (ENVIRONMENT != development):
  - Prefer validated IAP JWT (X-Goog-IAP-JWT-Assertion)
  - Otherwise accept X-User-Email when Cloud Run IAM already gated the request
  - Never trust X-User-Role for privilege escalation; resolve from email lists

Local development (ENVIRONMENT=development):
  - Accept X-User-Email / X-User-Role headers
  - Fall back to DEV_DEFAULT_USER / DEV_DEFAULT_ROLE
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Literal, Optional

from fastapi import Header, HTTPException, status

UserRole = Literal["technician", "finance_manager", "admin"]

logger = logging.getLogger(__name__)

IAP_CERTS_URL = "https://www.gstatic.com/iap/verify/public_key"


@dataclass(frozen=True)
class AuthenticatedUser:
    email: str
    role: UserRole


def _is_local_development(environment: str) -> bool:
    return environment == "development"


def _parse_email_set(env_var: str, default: str = "") -> set[str]:
    return {
        e.strip().lower()
        for e in os.getenv(env_var, default).split(",")
        if e.strip()
    }


def _resolve_role(email: str, explicit_role: Optional[str], *, trust_explicit_role: bool) -> UserRole:
    if trust_explicit_role and explicit_role in {"technician", "finance_manager", "admin"}:
        return explicit_role  # type: ignore[return-value]

    admin_emails = _parse_email_set("ADMIN_EMAILS")
    if email.lower() in admin_emails:
        return "admin"

    finance_emails = _parse_email_set(
        "FINANCE_MANAGER_EMAILS",
        "finance@roboreliance.internal",
    )
    if email.lower() in finance_emails:
        return "finance_manager"
    return "technician"


def _verify_iap_jwt(token: str) -> str:
    """
    Validate an IAP JWT and return the email claim.

    Requires IAP_AUDIENCE when non-empty (set after IAP is enabled).
    See: https://cloud.google.com/iap/docs/signed-headers-howto
    """
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="IAP validation unavailable: google-auth is not installed.",
        ) from exc

    audience = os.getenv("IAP_AUDIENCE", "").strip()
    request = google_requests.Request()

    try:
        if audience:
            claims = id_token.verify_token(
                token,
                request,
                audience=audience,
                certs_url=IAP_CERTS_URL,
            )
        else:
            # Audience not configured yet — still verify signature and expiry.
            claims = id_token.verify_token(
                token,
                request,
                audience=None,
                certs_url=IAP_CERTS_URL,
            )
            logger.warning(
                "IAP_AUDIENCE is unset; verified IAP JWT signature without audience check."
            )
    except Exception as exc:
        logger.warning("IAP JWT validation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid IAP assertion.",
        ) from exc

    email = claims.get("email")
    if not email or not isinstance(email, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="IAP assertion missing email claim.",
        )
    return email.strip()


async def get_current_user(
    x_user_email: Optional[str] = Header(default=None, alias="X-User-Email"),
    x_user_role: Optional[str] = Header(default=None, alias="X-User-Role"),
    x_goog_iap_jwt_assertion: Optional[str] = Header(
        default=None, alias="X-Goog-IAP-JWT-Assertion"
    ),
) -> AuthenticatedUser:
    environment = os.getenv("ENVIRONMENT", "development")
    local_dev = _is_local_development(environment)

    if x_goog_iap_jwt_assertion and not local_dev:
        email = _verify_iap_jwt(x_goog_iap_jwt_assertion)
        return AuthenticatedUser(
            email=email,
            role=_resolve_role(email, None, trust_explicit_role=False),
        )

    if not x_user_email:
        if local_dev:
            default_email = os.getenv("DEV_DEFAULT_USER", "field.tech@roboreliance.internal")
            return AuthenticatedUser(
                email=default_email,
                role=_resolve_role(
                    default_email,
                    os.getenv("DEV_DEFAULT_ROLE", "technician"),
                    trust_explicit_role=True,
                ),
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    email = x_user_email.strip()
    return AuthenticatedUser(
        email=email,
        role=_resolve_role(
            email,
            x_user_role,
            trust_explicit_role=local_dev,
        ),
    )


def require_finance_manager(user: AuthenticatedUser) -> None:
    if user.role not in {"finance_manager", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Finance manager role required.",
        )
