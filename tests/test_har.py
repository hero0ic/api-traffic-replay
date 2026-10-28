"""HAR import is a translator into the request-file schema."""

import json
from pathlib import Path

import pytest

from replay_core.har import HarError, import_har_file, load_har_json
from replay_core.loader import load_requests


def _har(entries: list[dict]) -> dict:
    return {"log": {"version": "1.2", "creator": {"name": "test", "version": "1"}, "entries": entries}}


def _entry(method: str, url: str, *, headers=None, post_data=None) -> dict:
    request = {
        "method": method,
        "url": url,
        "headers": headers or [],
        "queryString": [],
        "cookies": [],
        "httpVersion": "HTTP/1.1",
        "headersSize": -1,
        "bodySize": -1,
    }
    if post_data is not None:
        request["postData"] = post_data
    return {
        "startedDateTime": "2024-01-01T00:00:00.000Z",
        "time": 1,
        "request": request,
        "response": {"status": 200, "statusText": "OK", "headers": [], "content": {}, "cookies": []},
        "cache": {},
        "timings": {},
    }


def test_import_strips_secrets_and_keeps_path(tmp_path: Path) -> None:
    har = _har(
        [
            _entry(
                "GET",
                "https://api.example.com/v1/health",
                headers=[
                    {"name": "Authorization", "value": "Bearer secret"},
                    {"name": "Cookie", "value": "sid=1"},
                    {"name": "Accept", "value": "application/json"},
                ],
            )
        ]
    )
    path = tmp_path / "capture.har"
    path.write_text(json.dumps(har), encoding="utf-8")
    collection = import_har_file(path, name="demo", base_url="https://api.example.com/v1")
    assert collection.name == "demo"
    assert len(collection.requests) == 1
    spec = collection.requests[0]
    assert spec.method == "GET"
    assert spec.path == "/health"
    assert spec.headers == {"accept": "application/json"}
    assert "secret" not in json.dumps(spec.model_dump(mode="json", by_alias=True))


def test_import_json_post_body() -> None:
    har = _har(
        [
            _entry(
                "POST",
                "https://api.example.com/orders",
                headers=[{"name": "Content-Type", "value": "application/json"}],
                post_data={"mimeType": "application/json", "text": '{"sku":"A","qty":1}'},
            )
        ]
    )
    collection = load_har_json(har, name="orders")
    spec = collection.requests[0]
    assert spec.id.startswith("post-")
    assert spec.path == "/orders"
    assert spec.json_body == {"sku": "A", "qty": 1}
    assert spec.body is None


def test_import_raw_body_when_not_json() -> None:
    har = _har(
        [
            _entry(
                "POST",
                "https://api.example.com/echo",
                post_data={"mimeType": "text/plain", "text": "hello"},
            )
        ]
    )
    collection = load_har_json(har)
    assert collection.requests[0].body == "hello"
    assert collection.requests[0].json_body is None


def test_import_preserves_query_string() -> None:
    har = _har([_entry("GET", "https://api.example.com/delay?ms=20")])
    collection = load_har_json(har)
    assert collection.requests[0].path == "/delay?ms=20"


def test_import_rejects_empty_entries() -> None:
    with pytest.raises(HarError, match="non-empty"):
        load_har_json({"log": {"entries": []}})


def test_import_rejects_host_mismatch() -> None:
    har = _har([_entry("GET", "https://other.example.com/v1/health")])
    with pytest.raises(HarError, match="does not match"):
        load_har_json(har, base_url="https://api.example.com/v1")


def test_import_skips_non_http_schemes() -> None:
    har = _har(
        [
            _entry("GET", "ws://api.example.com/socket"),
            _entry("GET", "https://api.example.com/ok"),
        ]
    )
    collection = load_har_json(har)
    assert [item.path for item in collection.requests] == ["/ok"]


def test_unique_ids_for_duplicate_paths() -> None:
    har = _har(
        [
            _entry("GET", "https://api.example.com/items"),
            _entry("GET", "https://api.example.com/items"),
        ]
    )
    collection = load_har_json(har)
    ids = [item.id for item in collection.requests]
    assert ids[0] != ids[1]
    assert ids[0] == "get-items"
    assert ids[1] == "get-items-2"


def test_import_har_cli_writes_request_file(tmp_path: Path) -> None:
    from test_cli import run_cli

    har_path = tmp_path / "demo.har"
    out_path = tmp_path / "requests.json"
    har_path.write_text(
        json.dumps(
            _har(
                [
                    _entry(
                        "GET",
                        "http://127.0.0.1:8001/v1/health",
                        headers=[{"name": "Authorization", "value": "secret"}],
                    )
                ]
            )
        ),
        encoding="utf-8",
    )
    result = run_cli(
        [
            "import-har",
            "--har",
            str(har_path),
            "--out",
            str(out_path),
            "--name",
            "demo",
            "--base-url",
            "http://127.0.0.1:8001/v1",
        ]
    )
    assert result.returncode == 0, result.stderr
    assert "imported 1 requests" in result.stdout
    collection = load_requests(out_path)
    assert collection.name == "demo"
    assert collection.requests[0].path == "/health"
    assert "secret" not in out_path.read_text(encoding="utf-8")
