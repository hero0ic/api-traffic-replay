import asyncio

import httpx
import pytest

from replay_core.models import RequestSpec
from replay_core.runner import (
    UnsafeRequestsError,
    build_url,
    ensure_safe,
    execute,
    is_json_content_type,
)


def test_build_url_keeps_base_path() -> None:
    assert build_url("http://127.0.0.1:8000/v1", "/health") == "http://127.0.0.1:8000/v1/health"
    assert build_url("http://127.0.0.1:8000/v1/", "/health") == "http://127.0.0.1:8000/v1/health"
    assert build_url("http://127.0.0.1:8000", "/delay?ms=20") == "http://127.0.0.1:8000/delay?ms=20"


def test_json_content_type_detection() -> None:
    assert is_json_content_type("application/json")
    assert is_json_content_type("application/json; charset=utf-8")
    assert is_json_content_type("application/problem+json")
    assert not is_json_content_type("text/plain")
    assert not is_json_content_type("")


def test_get_and_head_do_not_require_unsafe() -> None:
    ensure_safe(
        [
            RequestSpec(id="read", method="GET", path="/"),
            RequestSpec(id="peek", method="HEAD", path="/"),
        ],
        unsafe=False,
    )


def test_mutating_method_requires_unsafe() -> None:
    spec = RequestSpec(id="create", method="POST", path="/orders", json_body={"sku": "A"})
    with pytest.raises(UnsafeRequestsError, match="create"):
        ensure_safe([spec], unsafe=False)


async def test_results_keep_request_order() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/slow":
            await asyncio.sleep(0.05)
        return httpx.Response(200, json={"path": request.url.path})

    attempts = await execute(
        "http://example.test",
        [
            RequestSpec(id="slow", method="GET", path="/slow"),
            RequestSpec(id="fast", method="GET", path="/fast"),
        ],
        transport=httpx.MockTransport(handler),
    )
    assert [item.exchange.id for item in attempts] == ["slow", "fast"]
    assert attempts[0].exchange.json_body == {"path": "/slow"}
    assert attempts[1].exchange.json_body == {"path": "/fast"}
    assert str(attempts[0].exchange.method) == "GET"


async def test_concurrency_limit_is_enforced() -> None:
    in_flight = 0
    peak = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        try:
            await asyncio.sleep(0.05)
            return httpx.Response(200, json={"ok": True})
        finally:
            in_flight -= 1

    specs = [RequestSpec(id=f"r{index}", method="GET", path=f"/{index}") for index in range(6)]
    await execute(
        "http://example.test",
        specs,
        concurrency=2,
        transport=httpx.MockTransport(handler),
    )
    assert peak == 2


async def test_timeout_is_an_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    attempts = await execute(
        "http://example.test",
        [RequestSpec(id="slow", method="GET", path="/slow")],
        timeout=0.1,
        transport=httpx.MockTransport(handler),
    )
    assert attempts[0].exchange.error == "timeout"
    assert attempts[0].exchange.status is None


async def test_response_headers_are_redacted() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "content-type": "application/json",
                "set-cookie": "session=secret",
                "date": "Mon, 01 Jan 2024 00:00:00 GMT",
                "server": "demo",
                "x-request-id": "abc",
            },
            json={"ok": True},
        )

    attempts = await execute(
        "http://example.test/v1/",
        [RequestSpec(id="health", method="GET", path="/health")],
        transport=httpx.MockTransport(handler),
    )
    headers = attempts[0].exchange.headers
    assert headers == {"content-type": "application/json"}
    assert "secret" not in str(headers)
    assert attempts[0].exchange.elapsed_ms is not None


async def test_json_secrets_are_redacted_on_capture() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"sku": "A", "password": "hunter2", "nested": {"token": "abc"}},
        )

    attempts = await execute(
        "http://example.test",
        [RequestSpec(id="secret", method="GET", path="/secret")],
        transport=httpx.MockTransport(handler),
    )
    assert attempts[0].exchange.json_body == {
        "sku": "A",
        "password": "***",
        "nested": {"token": "***"},
    }


async def test_invalid_json_is_stored_as_text() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/json"}, content=b"not-json")

    attempts = await execute(
        "http://example.test",
        [RequestSpec(id="broken", method="GET", path="/broken")],
        transport=httpx.MockTransport(handler),
    )
    exchange = attempts[0].exchange
    assert exchange.is_json is False
    assert exchange.body == "not-json"


async def test_unsafe_post_is_sent_when_enabled() -> None:
    seen: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url)))
        return httpx.Response(201, json={"id": "ord_1"})

    attempts = await execute(
        "http://example.test/v1",
        [RequestSpec(id="create", method="post", path="/orders", json_body={"sku": "A"})],
        unsafe=True,
        transport=httpx.MockTransport(handler),
    )
    assert seen == [("POST", "http://example.test/v1/orders")]
    assert attempts[0].exchange.status == 201
    assert attempts[0].exchange.json_body == {"id": "ord_1"}
