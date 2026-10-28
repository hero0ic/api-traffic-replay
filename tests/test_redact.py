from replay_core.redact import REDACTED_HEADERS, redact_headers


def test_denylist_covers_secrets_and_transfer_metadata() -> None:
    assert {
        "authorization",
        "cookie",
        "set-cookie",
        "date",
        "server",
        "content-length",
        "transfer-encoding",
        "connection",
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
        }
    )
    assert cleaned == {"x-request-id": "abc"}


def test_redact_does_not_mutate_input() -> None:
    original = {"Date": "t1", "X-Request-Id": "abc"}
    redact_headers(original)
    assert original == {"Date": "t1", "X-Request-Id": "abc"}
