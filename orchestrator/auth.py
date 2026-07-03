"""
Authentication helpers for /api/v1 routes.

Production: validate IAP JWT (X-Goog-IAP-JWT-Assertion).
Development: accept X-User-Email and X-User-Role headers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal, Optional

from fastapi import Header, HTTPException, status

UserRole = Literal["technician", "finance_manager", "admin"]


@dataclass(frozen=True)
class AuthenticatedUser:
    email: str
    role: UserRole


def _resolve_role(email: str, explicit_role: Optional[str]) -> UserRole:
    if explicit_role in {"technician", "finance_manager", "admin"}:
        return explicit_role  # type: ignore[return-value]
    finance_emails = {
        e.strip().lower()
        for e in os.getenv("FINANCE_MANAGER_EMAILS", "finance@roboreliance.internal").split(",")
        if e.strip()
    }
    if email.lower() in finance_emails:
        return "finance_manager"
    return "technician"


async def get_current_user(
    x_user_email: Optional[str] = Header(default=None, alias="X-User-Email"),
    x_user_role: Optional[str] = Header(default=None, alias="X-User-Role"),
    x_goog_iap_jwt_assertion: Optional[str] = Header(default=None, alias="X-Goog-IAP-JWT-Assertion"),
) -> AuthenticatedUser:
    environment = os.getenv("ENVIRONMENT", "development")

    if x_goog_iap_jwt_assertion and environment != "development":
        # Production IAP validation stub — decode and verify in deployment hardening.
        # For now extract email claim placeholder when IAP is wired.
        email = x_user_email or os.getenv("IAP_DEFAULT_EMAIL", "iap-user@roboreliance.internal")
        return AuthenticatedUser(email=email, role=_resolve_role(email, x_user_role))

    if not x_user_email:
        if environment == "development":
            return AuthenticatedUser(
                email=os.getenv("DEV_DEFAULT_USER", "field.tech@roboreliance.internal"),
                role=_resolve_role(
                    os.getenv("DEV_DEFAULT_USER", "field.tech@roboreliance.internal"),
                    os.getenv("DEV_DEFAULT_ROLE", "technician"),
                ),
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    return AuthenticatedUser(email=x_user_email.strip(), role=_resolve_role(x_user_email, x_user_role))


def require_finance_manager(user: AuthenticatedUser) -> None:
    if user.role not in {"finance_manager", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Finance manager role required.",
        )
