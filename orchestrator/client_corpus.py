"""
Multi-client SOP corpus resolution.

One agent (Geary); per-client Vertex AI Search engines. Resolve the serving
endpoint from visit.client_id → platform_configs.client_sop_endpoints, with
fallback to SOP_SEARCH_ENDPOINT.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_SOP_ENDPOINT = os.getenv(
    "SOP_SEARCH_ENDPOINT",
    "https://discoveryengine.googleapis.com/v1/projects/robo-reliance-ops/locations/global/"
    "collections/default_collection/engines/sop-library-search/servingConfigs/default_search",
)

# Optional JSON env overlay: {"chef": "https://.../engines/sop-chef/..."}
_ENV_CLIENT_SOP_JSON = os.getenv("CLIENT_SOP_ENDPOINTS", "").strip()

_CLIENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


def normalize_client_id(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    value = raw.strip().lower()
    if not value:
        return None
    if not _CLIENT_ID_RE.match(value):
        raise ValueError(
            f"Invalid client_id '{raw}'. Use lowercase letters, digits, _ or - "
            "(max 63 chars)."
        )
    return value


def _env_endpoint_map() -> Dict[str, str]:
    if not _ENV_CLIENT_SOP_JSON:
        return {}
    try:
        parsed = json.loads(_ENV_CLIENT_SOP_JSON)
    except json.JSONDecodeError:
        logger.warning("CLIENT_SOP_ENDPOINTS is not valid JSON; ignoring")
        return {}
    if not isinstance(parsed, dict):
        return {}
    out: Dict[str, str] = {}
    for key, value in parsed.items():
        if isinstance(key, str) and isinstance(value, str) and value.strip():
            out[key.strip().lower()] = value.strip()
    return out


def _db_endpoint_map() -> Dict[str, str]:
    try:
        from database import get_platform_config
    except Exception:
        return {}
    try:
        cfg = get_platform_config("client_sop_endpoints") or {}
    except Exception:
        logger.exception("Failed to load client_sop_endpoints from platform_configs")
        return {}
    if not isinstance(cfg, dict):
        return {}
    out: Dict[str, str] = {}
    for key, value in cfg.items():
        if isinstance(key, str) and isinstance(value, str) and value.strip():
            out[key.strip().lower()] = value.strip()
    return out


def resolve_sop_endpoint(client_id: Optional[str] = None) -> str:
    """
    Return the Discovery Engine servingConfig URL for a client.
    Falls back to shared SOP_SEARCH_ENDPOINT when client is unknown/unset.
    """
    normalized: Optional[str] = None
    try:
        normalized = normalize_client_id(client_id)
    except ValueError:
        logger.warning("Ignoring invalid client_id for SOP routing: %s", client_id)

    if normalized:
        merged = {}
        merged.update(_db_endpoint_map())
        merged.update(_env_endpoint_map())  # env wins
        endpoint = merged.get(normalized)
        if endpoint:
            return endpoint
        logger.info(
            "No client SOP endpoint for client_id=%s; using default SOP index",
            normalized,
        )
    return DEFAULT_SOP_ENDPOINT


def list_known_clients() -> Dict[str, Any]:
    """Return client registry for the web app (from platform_configs + defaults)."""
    default_client_id = "chef"
    clients: List[Dict[str, str]] = [
        {"id": "chef", "display_name": "Chef"},
        {"id": "roboreliance", "display_name": "Robo Reliance (internal)"},
    ]
    try:
        from database import get_platform_config

        cfg = get_platform_config("clients") or {}
        if isinstance(cfg, dict):
            if isinstance(cfg.get("default_client_id"), str) and cfg["default_client_id"].strip():
                default_client_id = cfg["default_client_id"].strip().lower()
            raw_clients = cfg.get("clients")
            if isinstance(raw_clients, list) and raw_clients:
                parsed: List[Dict[str, str]] = []
                for item in raw_clients:
                    if not isinstance(item, dict):
                        continue
                    cid = item.get("id")
                    name = item.get("display_name") or cid
                    if isinstance(cid, str) and cid.strip():
                        parsed.append(
                            {
                                "id": cid.strip().lower(),
                                "display_name": str(name).strip() or cid.strip(),
                            }
                        )
                if parsed:
                    clients = parsed
    except Exception:
        logger.exception("Failed to load clients registry; using defaults")

    return {"default_client_id": default_client_id, "clients": clients}
