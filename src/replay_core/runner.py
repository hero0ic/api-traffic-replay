"""Send the request file concurrently and capture one exchange per request.

The semaphore caps how many requests are in flight. Results are stored by
index so a slow first request still appears first in the report.
"""

import asyncio
import base64
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from replay_core.models import Exchange, RequestSpec
from replay_core.redact import redact_headers

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class UnsafeRequestsError(Exception):
    """A mutating method was present and --unsafe was not set."""

    def __init__(self, request_ids: list[str]) -> None:
        self.request_ids = request_ids
        super().__init__(
            "refusing to send POST, PUT, PATCH, or DELETE without --unsafe: "
            + ", ".join(request_ids)
        )


class TargetError(Exception):
    """The target was not an absolute http or https URL."""


@dataclass(frozen=True)
class Attempt:
    """One finished call, including time spent waiting for a free slot."""

    exchange: Exchange
    elapsed_ms: float


def validate_target(target: str) -> None:
    parsed = urlparse(target)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise TargetError("--target must be an absolute http or https URL")


def build_url(target: str, path: str) -> str:
    """Join a base URL and a request path without dropping a base path prefix.

    ``urllib.parse.urljoin`` treats a path that starts with ``/`` as absolute,
    so ``http://localhost/v1`` + ``/health`` would become ``http://localhost/health``.
    """

    return target.rstrip("/") + path


def ensure_safe(requests: list[RequestSpec], *, unsafe: bool) -> None:
    if unsafe:
        return
    blocked = [spec.id for spec in requests if spec.method in MUTATING_METHODS]
    if blocked:
        raise UnsafeRequestsError(blocked)


def is_json_content_type(content_type: str) -> bool:
    media = content_type.split(";", 1)[0].strip().lower()
    return media == "application/json" or media.endswith("+json")


async def execute(
    target: str,
    requests: list[RequestSpec],
    *,
    concurrency: int = 10,
    timeout: float = 10.0,
    unsafe: bool = False,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[Attempt]:
    """Replay every request. Transport errors become exchanges; they do not raise."""

    validate_target(target)
    ensure_safe(requests, unsafe=unsafe)
    semaphore = asyncio.Semaphore(concurrency)
    # The pool limit matches the semaphore so the cap is the one we can explain:
    # at most `concurrency` sockets, not an unbounded gather plus a hidden queue.
    limits = httpx.Limits(
        max_connections=concurrency,
        max_keepalive_connections=concurrency,
    )
    results: list[Attempt | None] = [None] * len(requests)

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout),
        limits=limits,
        transport=transport,
        follow_redirects=False,
        trust_env=False,
    ) as client:

        async def send(index: int, spec: RequestSpec) -> None:
            started = time.perf_counter()
            async with semaphore:
                exchange = await _perform(client, target, spec)
            elapsed_ms = (time.perf_counter() - started) * 1000
            results[index] = Attempt(exchange=exchange, elapsed_ms=elapsed_ms)

        await asyncio.gather(*(send(index, spec) for index, spec in enumerate(requests)))

    completed: list[Attempt] = []
    for item in results:
        if item is None:
            raise RuntimeError("a replay task finished without a result")
        completed.append(item)
    return completed


async def _perform(client: httpx.AsyncClient, target: str, spec: RequestSpec) -> Exchange:
    try:
        response = await client.request(
            spec.method,
            build_url(target, spec.path),
            headers=spec.headers,
            json=spec.json_body if spec.json_body is not None else None,
            content=None if spec.body is None else spec.body.encode("utf-8"),
        )
    except httpx.TimeoutException:
        return _failed(spec, "timeout")
    except httpx.HTTPError as exc:
        return _failed(spec, f"request failed: {exc}")
    return _from_response(spec, response)


def _failed(spec: RequestSpec, message: str) -> Exchange:
    return Exchange(id=spec.id, method=spec.method, path=spec.path, error=message)


def _from_response(spec: RequestSpec, response: httpx.Response) -> Exchange:
    headers = redact_headers(_header_map(response.headers))
    content_type = response.headers.get("content-type", "")
    if is_json_content_type(content_type):
        try:
            payload = response.json()
        except ValueError:
            text, encoding = _encode_body(response.content)
            return Exchange(
                id=spec.id,
                method=spec.method,
                path=spec.path,
                status=response.status_code,
                headers=headers,
                body=text,
                body_encoding=encoding,
                is_json=False,
            )
        return Exchange(
            id=spec.id,
            method=spec.method,
            path=spec.path,
            status=response.status_code,
            headers=headers,
            json_body=payload,
            is_json=True,
        )
    text, encoding = _encode_body(response.content)
    return Exchange(
        id=spec.id,
        method=spec.method,
        path=spec.path,
        status=response.status_code,
        headers=headers,
        body=text,
        body_encoding=encoding,
        is_json=False,
    )


def _header_map(headers: httpx.Headers) -> dict[str, str]:
    merged: dict[str, list[str]] = {}
    for key, value in headers.multi_items():
        merged.setdefault(key.lower(), []).append(value)
    return {key: ", ".join(values) for key, values in merged.items()}


def _encode_body(content: bytes) -> tuple[str, str]:
    try:
        return content.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return base64.b64encode(content).decode("ascii"), "base64"
