"""Sanitization for headers, query params, and JSON fields.

Headers are stripped before a baseline is saved and ignored during compare.
Query and JSON secret keys are replaced with a placeholder so HAR imports,
baselines, and AI prompts do not keep obvious credentials.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REDACTION_PLACEHOLDER = "***"

# Removed from stored responses and ignored during header compare.
REDACTED_HEADERS = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "date",
        "server",
        "content-length",
        "transfer-encoding",
        "connection",
        # Volatile correlation / CDN headers that change every request.
        "x-request-id",
        "x-correlation-id",
        "x-amzn-trace-id",
        "x-trace-id",
        "traceparent",
        "tracestate",
        "cf-ray",
        "x-cloud-trace-context",
    }
)

# Query param and JSON object keys replaced with a placeholder (case-insensitive).
SECRET_FIELD_NAMES = frozenset(
    {
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "id_token",
        "token",
        "password",
        "passwd",
        "secret",
        "client_secret",
        "private_key",
        "authorization",
        "auth",
        "session",
        "session_id",
        "jwt",
    }
)


def redact_headers(
    headers: dict[str, str],
    *,
    extra_ignore: list[str] | None = None,
) -> dict[str, str]:
    """Return a copy with header names lowercased and denied headers removed."""

    denied = set(REDACTED_HEADERS)
    if extra_ignore:
        denied.update(name.lower() for name in extra_ignore)
    return {
        key.lower(): value
        for key, value in headers.items()
        if key.lower() not in denied
    }


def is_secret_field_name(name: str) -> bool:
    return name.lower() in SECRET_FIELD_NAMES


def redact_json(value: Any) -> Any:
    """Deep-copy JSON-like data, replacing secret object keys with a placeholder."""

    if isinstance(value, dict):
        return {
            key: (REDACTION_PLACEHOLDER if is_secret_field_name(str(key)) else redact_json(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_json(item) for item in value]
    return value


def redact_query_string(path: str) -> str:
    """Redact denylisted query parameter values in a path-or-URL fragment."""

    split = urlsplit(path)
    if not split.query:
        return path
    pairs = []
    for key, value in parse_qsl(split.query, keep_blank_values=True):
        pairs.append((key, REDACTION_PLACEHOLDER if is_secret_field_name(key) else value))
    # Keep placeholders readable (*** not %2A%2A%2A) for checked-in request files.
    return urlunsplit(
        (
            split.scheme,
            split.netloc,
            split.path,
            urlencode(pairs, doseq=True, safe="*"),
            split.fragment,
        )
    )


def redact_request_path(path: str) -> str:
    """Sanitize a request path that may include a query string."""

    return redact_query_string(path)
