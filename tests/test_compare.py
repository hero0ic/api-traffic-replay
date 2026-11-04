import base64
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import replay_core
from replay_core.compare import build_report, compare_responses
from replay_core.loader import load_baseline, save_baseline
from replay_core.models import Baseline, Exchange, RequestCollection, RequestSpec

_MISSING = object()


def make_exchange(
    *,
    id: str = "req",
    method: str = "GET",
    path: str = "/",
    status: int | None = 200,
    payload: Any = _MISSING,
    headers: dict[str, str] | None = None,
    body: str | None = None,
    is_json: bool = True,
    body_encoding: str = "utf-8",
    error: str | None = None,
    elapsed_ms: float | None = None,
) -> Exchange:
    if payload is _MISSING:
        json_body = {} if is_json else None
    else:
        json_body = payload
    return Exchange(
        id=id,
        method=method,
        path=path,
        status=status,
        headers=headers or {},
        json_body=json_body,
        body=body,
        body_encoding=body_encoding,  # type: ignore[arg-type]
        is_json=is_json,
        error=error,
        elapsed_ms=elapsed_ms,
    )


CASES = [
    {
        "name": "status change",
        "baseline": {"payload": {"ok": True}},
        "candidate": {"status": 422, "payload": {"ok": True}},
        "ignore": [],
        "expected": [("status", "", "replace", 200, 422)],
    },
    {
        "name": "missing json field",
        "baseline": {"payload": {"sku": "A", "qty": 1}},
        "candidate": {"payload": {"sku": "A"}},
        "ignore": [],
        "expected": [("json", "qty", "remove", 1, None)],
    },
    {
        "name": "extra json field",
        "baseline": {"payload": {"sku": "A"}},
        "candidate": {"payload": {"sku": "A", "note": "x"}},
        "ignore": [],
        "expected": [("json", "note", "add", None, "x")],
    },
    {
        "name": "ignored timestamp",
        "baseline": {"payload": {"id": 1, "created_at": "t1"}},
        "candidate": {"payload": {"id": 1, "created_at": "t2"}},
        "ignore": ["created_at"],
        "expected": [],
    },
    {
        "name": "key order independence",
        "baseline": {"payload": {"b": 2, "a": 1}},
        "candidate": {"payload": {"a": 1, "b": 2}},
        "ignore": [],
        "expected": [],
    },
    {
        "name": "array reorder",
        "baseline": {"payload": [1, 2]},
        "candidate": {"payload": [2, 1]},
        "ignore": [],
        "expected": [
            ("json", "0", "replace", 1, 2),
            ("json", "1", "replace", 2, 1),
        ],
    },
    {
        "name": "longer array",
        "baseline": {"payload": [1]},
        "candidate": {"payload": [1, 2]},
        "ignore": [],
        "expected": [("json", "1", "add", None, 2)],
    },
    {
        "name": "header denylist",
        "baseline": {
            "headers": {
                "Authorization": "secret-a",
                "Cookie": "a=1",
                "Set-Cookie": "session=a",
                "Date": "t1",
                "Server": "one",
                "X-Request-Id": "same",
            }
        },
        "candidate": {
            "headers": {
                "authorization": "secret-b",
                "cookie": "b=2",
                "set-cookie": "session=b",
                "date": "t2",
                "server": "two",
                "x-request-id": "same",
            }
        },
        "ignore": [],
        "expected": [],
    },
    {
        "name": "content length is transfer metadata",
        "baseline": {"headers": {"Content-Length": "4"}, "payload": {"ok": True}},
        "candidate": {"headers": {"Content-Length": "9"}, "payload": {"ok": True}},
        "ignore": [],
        "expected": [],
    },
    {
        "name": "content type is compared",
        "baseline": {"headers": {"Content-Type": "application/json"}, "payload": {"ok": True}},
        "candidate": {"headers": {"Content-Type": "text/plain"}, "payload": {"ok": True}},
        "ignore": [],
        "expected": [
            ("header", "content-type", "replace", "application/json", "text/plain"),
        ],
    },
    {
        "name": "volatile request id header is ignored",
        "baseline": {"headers": {"X-Request-Id": "abc"}},
        "candidate": {"headers": {"X-Request-Id": "xyz"}},
        "ignore": [],
        "expected": [],
    },
    {
        "name": "custom header value change",
        "baseline": {"headers": {"X-Api-Version": "1"}},
        "candidate": {"headers": {"X-Api-Version": "2"}},
        "ignore": [],
        "expected": [("header", "x-api-version", "replace", "1", "2")],
    },
    {
        "name": "json to empty plaintext is a regression",
        "baseline": {"payload": {"ok": True}},
        "candidate": {"is_json": False, "body": ""},
        "ignore": [],
        "expected": [("body", "", "replace", '{"ok":true}', "")],
    },
    {
        "name": "json to plaintext body is a regression",
        "baseline": {"payload": {"ok": True}},
        "candidate": {"is_json": False, "body": "ok"},
        "ignore": [],
        "expected": [("body", "", "replace", '{"ok":true}', "ok")],
    },
    {
        "name": "non-json body change",
        "baseline": {"is_json": False, "body": "hello"},
        "candidate": {"is_json": False, "body": "world"},
        "ignore": [],
        "expected": [("body", "", "replace", "hello", "world")],
    },
    {
        "name": "equivalent non-json encodings match",
        "baseline": {"is_json": False, "body": "hi"},
        "candidate": {
            "is_json": False,
            "body": base64.b64encode(b"hi").decode("ascii"),
            "body_encoding": "base64",
        },
        "ignore": [],
        "expected": [],
    },
    {
        "name": "wildcard ignore",
        "baseline": {"payload": {"items": [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]}},
        "candidate": {"payload": {"items": [{"id": 9, "name": "a"}, {"id": 8, "name": "b"}]}},
        "ignore": ["items.*.id"],
        "expected": [],
    },
    {
        "name": "wildcard does not hide other fields",
        "baseline": {"payload": {"items": [{"id": 1, "name": "a"}]}},
        "candidate": {"payload": {"items": [{"id": 9, "name": "z"}]}},
        "ignore": ["items.*.id"],
        "expected": [("json", "items.0.name", "replace", "a", "z")],
    },
    {
        "name": "ignored object hides nested fields",
        "baseline": {"payload": {"user": {"name": "a"}}},
        "candidate": {"payload": {"user": {"name": "b"}}},
        "ignore": ["user"],
        "expected": [],
    },
    {
        "name": "bool is not a number",
        "baseline": {"payload": True},
        "candidate": {"payload": 1},
        "ignore": [],
        "expected": [("json", "", "replace", True, 1)],
    },
]


def test_package_version() -> None:
    assert replay_core.__version__ == "0.1.0"


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_compare_table(case: dict[str, Any]) -> None:
    diffs = compare_responses(
        make_exchange(**case["baseline"]),
        make_exchange(**case["candidate"]),
        case["ignore"],
    )
    actual = [(diff.kind, diff.path, diff.op, diff.baseline, diff.candidate) for diff in diffs]
    assert actual == case["expected"]


def test_request_rejects_json_and_raw_body() -> None:
    with pytest.raises(ValidationError):
        RequestSpec.model_validate(
            {
                "id": "create",
                "method": "POST",
                "path": "/orders",
                "json": {"sku": "A"},
                "body": "raw",
            }
        )


def test_duplicate_ids_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate request ids"):
        RequestCollection.model_validate(
            {
                "name": "orders",
                "requests": [
                    {"id": "same", "method": "GET", "path": "/"},
                    {"id": "same", "method": "GET", "path": "/other"},
                ],
            }
        )


def test_ignore_path_rejects_empty_segment() -> None:
    with pytest.raises(ValidationError, match="invalid ignore path"):
        RequestCollection.model_validate(
            {
                "name": "orders",
                "ignore": ["items..id"],
                "requests": [{"id": "a", "method": "GET", "path": "/"}],
            }
        )


def test_path_must_start_with_slash() -> None:
    with pytest.raises(ValidationError, match="path must start with /"):
        RequestSpec.model_validate({"id": "a", "method": "GET", "path": "orders"})


def test_build_report_counts_each_outcome() -> None:
    specs = [
        RequestSpec(id="ok", method="GET", path="/ok"),
        RequestSpec(id="bad", method="GET", path="/bad"),
        RequestSpec(id="down", method="GET", path="/down"),
    ]
    baseline = [
        make_exchange(id="ok", path="/ok", payload={"n": 1}),
        make_exchange(id="bad", path="/bad", payload={"n": 1}),
        make_exchange(id="down", path="/down", payload={"n": 1}),
    ]
    candidate = [
        make_exchange(id="ok", path="/ok", payload={"n": 1}),
        make_exchange(id="bad", path="/bad", payload={"n": 2}),
        make_exchange(id="down", path="/down", status=None, is_json=False, error="timeout"),
    ]
    report = build_report("demo", specs, baseline, candidate, ignore=[])
    assert report.summary.model_dump() == {
        "total": 3,
        "matched": 1,
        "regressed": 1,
        "errored": 1,
    }
    assert [item.outcome for item in report.results] == ["matched", "regressed", "errored"]
    assert report.results[2].error == "timeout"


def test_missing_baseline_is_an_error() -> None:
    spec = RequestSpec(id="health", method="GET", path="/health")
    report = build_report(
        "demo",
        [spec],
        [],
        [make_exchange(id="health", path="/health", payload={"ok": True})],
        ignore=[],
    )
    assert report.results[0].outcome == "errored"
    assert report.results[0].error == "no baseline recorded for health"


def test_failed_baseline_is_not_a_match() -> None:
    spec = RequestSpec(id="health", method="GET", path="/health")
    report = build_report(
        "demo",
        [spec],
        [make_exchange(id="health", path="/health", status=None, is_json=False, error="timeout")],
        [make_exchange(id="health", path="/health", payload={"ok": True})],
        ignore=[],
    )
    assert report.results[0].outcome == "errored"
    assert report.results[0].error == "baseline request failed: timeout"


def test_extra_ignore_header_suppresses_custom_header() -> None:
    diffs = compare_responses(
        make_exchange(headers={"X-Api-Version": "1"}),
        make_exchange(headers={"X-Api-Version": "2"}),
        ignore=[],
        ignore_headers=["x-api-version"],
    )
    assert diffs == []


def test_identity_mismatch_is_an_error() -> None:
    spec = RequestSpec(id="user", method="GET", path="/users/2")
    baseline = [make_exchange(id="user", path="/users/1", payload={"ok": True})]
    candidate = [make_exchange(id="user", path="/users/2", payload={"ok": True})]
    report = build_report("demo", [spec], baseline, candidate, ignore=[])
    assert report.results[0].outcome == "errored"
    assert "identity mismatch" in (report.results[0].error or "")


def test_latency_regression_uses_threshold() -> None:
    baseline = make_exchange(payload={"ok": True}, status=200, elapsed_ms=100.0)
    candidate = make_exchange(payload={"ok": True}, status=200, elapsed_ms=500.0)
    diffs = compare_responses(baseline, candidate, ignore=[], check_latency=True)
    assert [(diff.kind, diff.baseline, diff.candidate) for diff in diffs] == [
        ("latency", 100.0, 500.0)
    ]
    ignored = compare_responses(baseline, candidate, ignore=[], check_latency=False)
    assert ignored == []


def test_baseline_round_trip(tmp_path: Path) -> None:
    original = Baseline(
        name="demo",
        target="http://127.0.0.1:9/v1",
        exchanges=[
            make_exchange(id="null-body", payload=None),
            make_exchange(
                id="bytes",
                is_json=False,
                body=base64.b64encode(b"\xff").decode("ascii"),
                body_encoding="base64",
            ),
        ],
    )
    path = tmp_path / "nested" / "baseline.json"
    save_baseline(path, original)
    text = path.read_text(encoding="utf-8")
    assert "json_body" not in text
    assert '"json": null' in text
    assert load_baseline(path) == original
