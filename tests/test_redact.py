from replay_core.redact import (
    REDACTED_HEADERS,
    REDACTION_PLACEHOLDER,
    redact_headers,
    redact_json,
    redact_request_path,
)


def test_denylist_covers_secrets_transfer_and_volatile_headers() -> None:
    assert {
        "authorization",
        "cookie",
        "set-cookie",
        "date",
        "server",
        "content-length",
        "transfer-encoding",
        "connection",
        "x-request-id",
        "x-correlation-id",
        "x-amzn-trace-id",
        "x-trace-id",
        "traceparent",
        "tracestate",
        "cf-ray",
        "x-cloud-trace-context",
    } == REDACTED_HEADERS


def test_redact_removes_denied_headers_case_insensitively() -> None:
    cleaned = redact_headers(
        {
            "Date": "Mon, 01 Jan 2024 00:00:00 GMT",
            "Server": "demo",
            "Authorization": "secret",
            "Cookie": "a=1",
            "Set-Cookie": "session=secret",
            "Content-Length": "12",
            "X-Request-Id": "abc",
            "X-Custom": "keep",
        }
    )
    assert cleaned == {"x-custom": "keep"}


def test_extra_ignore_headers() -> None:
    cleaned = redact_headers(
        {"X-Custom": "a", "X-Keep": "b"},
        extra_ignore=["x-custom"],
    )
    assert cleaned == {"x-keep": "b"}


def test_redact_does_not_mutate_input() -> None:
    original = {"Date": "t1", "X-Custom": "abc"}
    redact_headers(original)
    assert original == {"Date": "t1", "X-Custom": "abc"}


def test_redact_query_secrets() -> None:
    path = redact_request_path("/users?api_key=SECRET_VALUE&page=1")
    assert "SECRET_VALUE" not in path
    assert f"api_key={REDACTION_PLACEHOLDER}" in path
    assert "page=1" in path


def test_redact_json_secret_fields() -> None:
    payload = {
        "sku": "A",
        "password": "hunter2",
        "nested": {"token": "abc", "ok": True},
        "items": [{"access_token": "x", "id": 1}],
    }
    cleaned = redact_json(payload)
    assert cleaned["sku"] == "A"
    assert cleaned["password"] == REDACTION_PLACEHOLDER
    assert cleaned["nested"]["token"] == REDACTION_PLACEHOLDER
    assert cleaned["nested"]["ok"] is True
    assert cleaned["items"][0]["access_token"] == REDACTION_PLACEHOLDER
    assert cleaned["items"][0]["id"] == 1
