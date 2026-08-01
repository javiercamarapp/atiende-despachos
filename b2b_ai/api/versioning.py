# -*- coding: utf-8 -*-
"""
versioning.py — API Versioning Enterprise.

Supports simultaneous /api/v1/ and /api/v2/ with:
  - Deprecation warnings in headers for v1
  - Version negotiation via Accept-Version header
  - Sunset dates for deprecated versions
  - X-API-Version header in all responses

Usage:
    from b2b_ai.api.versioning import install_versioning
    install_versioning(app)
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

# Version registry: each version has a deprecation date and sunset date.
# None means the version is current and fully supported.
VERSION_REGISTRY: dict[str, dict] = {
    "v1": {
        "status": "deprecated",
        "deprecated_since": "2026-01-01",
        "sunset_date": "2027-01-01",
        "message": (
            "API v1 is deprecated and will be removed on 2027-01-01. "
            "Please migrate to v2. See https://docs.b2b-ai.local/migration/v1-to-v2"
        ),
    },
    "v2": {
        "status": "current",
        "deprecated_since": None,
        "sunset_date": None,
        "message": None,
    },
}

# Pattern to detect versioned API paths.
_VERSION_PATH_RE = re.compile(r"^/api/(v\d+)/")

# Default version when no Accept-Version header is present.
DEFAULT_VERSION = "v2"

# Maximum supported version (for forward-compat rejection).
MAX_VERSION = 2


def _parse_accept_version(header: Optional[str]) -> Optional[str]:
    """Parse Accept-Version header. Supports: v1, v2, 1, 2."""
    if not header:
        return None
    val = header.strip().lower()
    # Normalize: accept "v1" or "1"
    if val.isdigit():
        val = f"v{val}"
    if val.startswith("v") and val[1:].isdigit():
        return val
    return None


def _version_from_path(path: str) -> Optional[str]:
    """Extract version from path like /api/v1/..."""
    m = _VERSION_PATH_RE.match(path)
    return m.group(1) if m else None


def _is_versioned_path(path: str) -> bool:
    return bool(_VERSION_PATH_RE.match(path))


class VersioningMiddleware(BaseHTTPMiddleware):
    """Inject versioning headers and handle version negotiation.

    For /api/v{N}/ paths:
      - Sets X-API-Version response header
      - Adds Deprecation and Sunset headers for deprecated versions
      - Respects Accept-Version header for version negotiation
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path

        # Only apply to versioned API paths
        if not _is_versioned_path(path):
            return await call_next(request)

        path_version = _version_from_path(path)
        accept_version = _parse_accept_version(
            request.headers.get("accept-version")
        )

        # If Accept-Version conflicts with path version, return 400
        if accept_version and path_version and accept_version != path_version:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "code": 1001,
                        "type": "version_conflict",
                        "message": (
                            f"Accept-Version header '{accept_version}' conflicts "
                            f"with URL path version '{path_version}'. "
                            f"Use one or the other, not both."
                        ),
                    }
                },
            )

        # Check if requested version exists
        version = accept_version or path_version
        if version and version not in VERSION_REGISTRY:
            from fastapi.responses import JSONResponse
            available = [v for v, info in VERSION_REGISTRY.items()
                         if info["status"] != "removed"]
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "code": 1002,
                        "type": "unsupported_version",
                        "message": f"API version '{version}' is not supported.",
                        "available_versions": sorted(available),
                    }
                },
            )

        # Process the request
        response = await call_next(request)

        # Inject version headers
        if version:
            info = VERSION_REGISTRY.get(version, {})
            response.headers["X-API-Version"] = version

            # Deprecation headers for deprecated versions
            if info.get("status") == "deprecated":
                # RFC 8594 Deprecation header
                dep_since = info.get("deprecated_since", "")
                if dep_since:
                    response.headers["Deprecation"] = f"date={dep_since}"
                # Sunset header (RFC 8594)
                sunset = info.get("sunset_date")
                if sunset:
                    response.headers["Sunset"] = sunset
                # Link header to migration docs
                response.headers["Link"] = (
                    '</api/v2>; rel="successor-version"'
                )
                # Warning header (RFC 7234 §5.5)
                msg = info.get("message", "")
                if msg:
                    # Warning header: warn-code warn-agent "warn-text" warn-date
                    response.headers["Warning"] = (
                        f'299 b2b-ai "{msg}"'
                    )

        return response


def install_versioning(app) -> None:
    """Install versioning middleware on the FastAPI app."""
    app.add_middleware(VersioningMiddleware)


def get_version_info(version: str) -> Optional[dict]:
    """Get version registry info for a given version string."""
    return VERSION_REGISTRY.get(version)


def deprecate_version(
    version: str,
    deprecated_since: str,
    sunset_date: str,
    message: str,
) -> None:
    """Mark a version as deprecated (runtime call)."""
    if version in VERSION_REGISTRY:
        VERSION_REGISTRY[version]["status"] = "deprecated"
        VERSION_REGISTRY[version]["deprecated_since"] = deprecated_since
        VERSION_REGISTRY[version]["sunset_date"] = sunset_date
        VERSION_REGISTRY[version]["message"] = message
