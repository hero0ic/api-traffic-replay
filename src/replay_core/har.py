"""Translate a HAR capture into the request-file schema.

HAR is the interoperable import format. This module is a translator only; the
replay engine still runs on ``RequestCollection``, not on HAR itself.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

from replay_core.models import RequestCollection, RequestSpec

# Request headers that should not be copied into a checked-in request file.
STRIP_REQUEST_HEADERS = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "content-length",
        "host",
        "connection",
        "transfer-encoding",
        "keep-alive",
        "proxy-connection",
        "upgrade",
    }
)


class HarError(ValueError):
    """The HAR file could not be converted into a request collection."""


def load_har_json(data: Any, *, name: str = "imported", base_url: str | None = None) -> RequestCollection:
    """Convert a parsed HAR document into a ``RequestCollection``."""

    if not isinstance(data, dict):
        raise HarError("HAR root must be a JSON object")
    log = data.get("log")
    if not isinstance(log, dict):
        raise HarError("HAR missing log object")
    entries = log.get("entries")
    if not isinstance(entries, list) or not entries:
        raise HarError("HAR log.entries must be a non-empty list")

    base = _normalize_base(base_url) if base_url else None
    requests: list[RequestSpec] = []
    used_ids: set[str] = set()

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise HarError(f"entries[{index}] must be an object")
        request = entry.get("request")
        if not isinstance(request, dict):
            raise HarError(f"entries[{index}].request missing")
        spec = _entry_to_spec(request, index=index, base=base, used_ids=used_ids)
        if spec is not None:
            requests.append(spec)

    if not requests:
        raise HarError("no HTTP requests found in HAR")
    return RequestCollection(name=name, requests=requests)


def import_har_file(
    path: Any,
    *,
    name: str = "imported",
    base_url: str | None = None,
) -> RequestCollection:
    """Read a HAR file from disk and convert it."""

    from pathlib import Path

    file_path = Path(path)
    try:
        raw = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HarError(str(exc)) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HarError(f"{file_path}: invalid JSON on line {exc.lineno}") from exc
    return load_har_json(data, name=name, base_url=base_url)


def _normalize_base(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HarError("--base-url must be an absolute http or https URL")
    return base_url.rstrip("/")


def _entry_to_spec(
    request: dict[str, Any],
    *,
    index: int,
    base: str | None,
    used_ids: set[str],
) -> RequestSpec | None:
    method = str(request.get("method") or "").strip().upper()
    url = str(request.get("url") or "").strip()
    if not method or not url:
        raise HarError(f"entries[{index}] missing method or url")

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return None

    path = _path_for_request(parsed, base=base, index=index)
    headers = _headers_from_har(request.get("headers"))
    json_body, body = _body_from_har(request.get("postData"))

    request_id = _unique_id(method, path, index, used_ids)
    return RequestSpec(
        id=request_id,
        method=method,
        path=path,
        headers=headers,
        json_body=json_body,
        body=body,
    )


def _path_for_request(parsed: Any, *, base: str | None, index: int) -> str:
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    if not path.startswith("/"):
        path = "/" + path

    if base is None:
        return path

    base_parsed = urlparse(base)
    if parsed.scheme != base_parsed.scheme or parsed.netloc != base_parsed.netloc:
        raise HarError(
            f"entries[{index}] URL host {parsed.netloc!r} does not match --base-url host "
            f"{base_parsed.netloc!r}"
        )

    base_path = base_parsed.path.rstrip("/")
    if base_path and path.startswith(base_path + "/"):
        remainder = path[len(base_path) :]
        return remainder if remainder.startswith("/") else "/" + remainder
    if base_path and path == base_path:
        return "/"
    if base_path and not path.startswith(base_path):
        # Path is already site-root relative; keep it.
        return path
    return path


def _headers_from_har(raw: Any) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, list):
        raise HarError("request.headers must be a list")
    headers: dict[str, str] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name or name.lower() in STRIP_REQUEST_HEADERS:
            continue
        headers[name.lower()] = str(item.get("value") or "")
    return headers


def _body_from_har(post_data: Any) -> tuple[Any, str | None]:
    if post_data is None:
        return None, None
    if not isinstance(post_data, dict):
        raise HarError("request.postData must be an object")
    text = post_data.get("text")
    if text is None:
        return None, None
    if not isinstance(text, str):
        raise HarError("request.postData.text must be a string")
    mime = str(post_data.get("mimeType") or "").split(";", 1)[0].strip().lower()
    if mime == "application/json" or mime.endswith("+json"):
        try:
            return json.loads(text), None
        except json.JSONDecodeError:
            return None, text
    return None, text


def _unique_id(method: str, path: str, index: int, used_ids: set[str]) -> str:
    path_part = path.split("?", 1)[0].strip("/") or "root"
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", path_part).strip("-").lower() or "root"
    base = f"{method.lower()}-{slug}"[:80]
    candidate = base
    suffix = 2
    while candidate in used_ids:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used_ids.add(candidate)
    return candidate

