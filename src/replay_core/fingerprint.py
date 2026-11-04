"""Stable fingerprint of a request collection.

Baselines store this hash so ``replay run`` can refuse a requests file that no
longer matches what was recorded, even when request ids were reused.
"""

from __future__ import annotations

import hashlib
import json

from replay_core.models import RequestCollection, RequestSpec


def fingerprint_requests(collection: RequestCollection) -> str:
    """Return a hex SHA-256 over normalized request identities and payloads."""

    payload = [_fingerprint_spec(spec) for spec in collection.requests]
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _fingerprint_spec(spec: RequestSpec) -> dict:
    return {
        "id": spec.id,
        "method": spec.method,
        "path": spec.path,
        "headers": {key.lower(): value for key, value in sorted(spec.headers.items())},
        "json": spec.json_body,
        "body": spec.body,
    }
