"""Header filtering applied before a baseline is saved and again during compare.

Saving a baseline should not keep secrets, and compare should not flag headers
that describe the HTTP transfer rather than the API payload.
"""

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
    }
)


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    """Return a copy with header names lowercased and denied headers removed."""

    return {
        key.lower(): value
        for key, value in headers.items()
        if key.lower() not in REDACTED_HEADERS
    }
