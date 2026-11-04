import json
import os
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def run_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    src = str(ROOT / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "replay_core.cli", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )


def test_help_lists_commands() -> None:
    result = run_cli(["--help"])
    assert result.returncode == 0
    assert "record" in result.stdout
    assert "run" in result.stdout


def test_record_refuses_post_without_unsafe(tmp_path: Path) -> None:
    requests_path = tmp_path / "requests.json"
    requests_path.write_text(
        json.dumps(
            {
                "name": "orders",
                "requests": [
                    {"id": "create", "method": "post", "path": "/orders", "json": {"sku": "A"}},
                ],
            }
        ),
        encoding="utf-8",
    )
    result = run_cli(
        [
            "record",
            "--target",
            "http://127.0.0.1:9",
            "--requests",
            str(requests_path),
            "--out",
            str(tmp_path / "baseline.json"),
        ]
    )
    assert result.returncode == 2
    assert "unsafe" in result.stderr


def test_fingerprint_mismatch_exits_2(tmp_path: Path) -> None:
    requests_path = tmp_path / "requests.json"
    baseline_path = tmp_path / "baseline.json"
    requests_path.write_text(
        json.dumps({"name": "demo", "requests": [{"id": "a", "method": "GET", "path": "/a"}]}),
        encoding="utf-8",
    )
    baseline_path.write_text(
        json.dumps(
            {
                "name": "demo",
                "target": "http://127.0.0.1:9",
                "requests_fingerprint": "not-the-real-hash",
                "exchanges": [
                    {
                        "id": "a",
                        "method": "GET",
                        "path": "/a",
                        "status": 200,
                        "headers": {},
                        "json": {"ok": True},
                        "is_json": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result = run_cli(
        [
            "run",
            "--target",
            "http://127.0.0.1:9",
            "--requests",
            str(requests_path),
            "--baseline",
            str(baseline_path),
            "--out",
            str(tmp_path / "report.json"),
        ]
    )
    assert result.returncode == 2
    assert "fingerprint" in result.stderr


def test_invalid_request_file_exits_2(tmp_path: Path) -> None:
    requests_path = tmp_path / "requests.json"
    requests_path.write_text("{", encoding="utf-8")
    result = run_cli(
        [
            "record",
            "--target",
            "http://127.0.0.1:9",
            "--requests",
            str(requests_path),
            "--out",
            str(tmp_path / "baseline.json"),
        ]
    )
    assert result.returncode == 2
    assert "invalid JSON" in result.stderr


def test_target_must_be_absolute_http_url(tmp_path: Path) -> None:
    requests_path = tmp_path / "requests.json"
    requests_path.write_text(
        json.dumps({"name": "demo", "requests": [{"id": "health", "method": "GET", "path": "/health"}]}),
        encoding="utf-8",
    )
    result = run_cli(
        [
            "record",
            "--target",
            "localhost:8000",
            "--requests",
            str(requests_path),
            "--out",
            str(tmp_path / "baseline.json"),
        ]
    )
    assert result.returncode == 2
    assert "--target" in result.stderr


def test_record_and_run_round_trip_exit_codes(tmp_path: Path) -> None:
    state = {"status": 200, "body": b'{"ok": true}'}
    with _http_server(state) as base:
        requests_path = tmp_path / "requests.json"
        baseline_path = tmp_path / "baseline.json"
        report_path = tmp_path / "report.json"
        requests_path.write_text(
            json.dumps({"name": "probe", "requests": [{"id": "root", "method": "GET", "path": "/"}]}),
            encoding="utf-8",
        )
        recorded = run_cli(
            ["record", "--target", base, "--requests", str(requests_path), "--out", str(baseline_path)]
        )
        assert recorded.returncode == 0, recorded.stderr
        saved = baseline_path.read_text(encoding="utf-8")
        assert "secret" not in saved
        assert "set-cookie" not in saved.lower()
        assert "json_body" not in saved

        matched = run_cli(
            [
                "run",
                "--target",
                base,
                "--requests",
                str(requests_path),
                "--baseline",
                str(baseline_path),
                "--out",
                str(report_path),
            ]
        )
        assert matched.returncode == 0, matched.stderr
        assert "1 total, 1 matched, 0 regressed, 0 errored" in matched.stdout

        state["status"] = 500
        state["body"] = b'{"ok": false}'
        changed = run_cli(
            [
                "run",
                "--target",
                base,
                "--requests",
                str(requests_path),
                "--baseline",
                str(baseline_path),
                "--out",
                str(report_path),
                "--format",
                "json",
            ]
        )
        assert changed.returncode == 1, changed.stderr
        report = json.loads(changed.stdout)
        assert report == json.loads(report_path.read_text(encoding="utf-8"))
        assert report["summary"]["regressed"] == 1
        assert report["results"][0]["diffs"][0]["kind"] == "status"


def test_timeout_is_reported_as_an_error(tmp_path: Path) -> None:
    requests_path = tmp_path / "requests.json"
    requests_path.write_text(
        json.dumps(
            {
                "name": "slow",
                "requests": [{"id": "delay", "method": "GET", "path": "/delay?ms=1000"}],
            }
        ),
        encoding="utf-8",
    )
    with _demo_server(tmp_path) as base:
        result = run_cli(
            [
                "record",
                "--target",
                base,
                "--requests",
                str(requests_path),
                "--out",
                str(tmp_path / "baseline.json"),
                "--timeout",
                "0.2",
            ]
        )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "delay: timeout" in result.stderr


def test_demo_api_replay_finds_planted_regressions(tmp_path: Path) -> None:
    requests_path = ROOT / "examples" / "demo_api" / "requests.json"
    with _demo_server(tmp_path) as base:
        live = httpx.get(f"{base}/v1/health", timeout=2)
        assert live.status_code == 200
        assert "secret" in live.headers.get("set-cookie", "")

        baseline_path = tmp_path / "baseline.json"
        report_path = tmp_path / "report.json"
        recorded = run_cli(
            [
                "record",
                "--target",
                f"{base}/v1",
                "--requests",
                str(requests_path),
                "--out",
                str(baseline_path),
            ]
        )
        assert recorded.returncode == 0, recorded.stderr
        saved = baseline_path.read_text(encoding="utf-8")
        assert "secret" not in saved
        assert "set-cookie" not in saved.lower()

        replayed = run_cli(
            [
                "run",
                "--target",
                f"{base}/v2",
                "--requests",
                str(requests_path),
                "--baseline",
                str(baseline_path),
                "--out",
                str(report_path),
            ]
        )
        assert replayed.returncode == 1, replayed.stdout + replayed.stderr
        assert "REGRESSED health" in replayed.stdout
        assert replayed.stdout.index("REGRESSED health") < replayed.stdout.index("REGRESSED order")
        assert "REGRESSED clock" not in replayed.stdout

        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["summary"] == {"total": 3, "matched": 1, "regressed": 2, "errored": 0}
        by_id = {item["id"]: item for item in report["results"]}
        assert [(diff["kind"], diff["path"]) for diff in by_id["health"]["diffs"]] == [
            ("status", ""),
            ("json", "status"),
        ]
        assert [(diff["op"], diff["path"]) for diff in by_id["order"]["diffs"]] == [
            ("add", "product_sku"),
            ("remove", "sku"),
        ]
        # clock differs only in created_at, which the request file ignores.
        assert by_id["clock"]["outcome"] == "matched"
        assert by_id["clock"]["diffs"] == []


@contextmanager
def _http_server(state: dict[str, object]):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = state["body"]
            assert isinstance(body, bytes)
            self.send_response(int(state["status"]))
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Set-Cookie", "session=secret")
            self.send_header("Date", "Mon, 01 Jan 2024 00:00:00 GMT")
            self.send_header("X-Request-Id", "abc")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()


@contextmanager
def _demo_server(tmp_path: Path):
    port = _free_port()
    stderr_path = tmp_path / "uvicorn.err"
    stderr_file = stderr_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app:app",
            "--app-dir",
            str(ROOT / "examples" / "demo_api"),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=stderr_file,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 15
        while time.time() < deadline:
            if proc.poll() is not None:
                stderr_file.flush()
                raise RuntimeError(stderr_path.read_text(encoding="utf-8"))
            try:
                response = httpx.get(f"{base}/v1/health", timeout=0.5)
            except httpx.HTTPError:
                time.sleep(0.1)
                continue
            if response.status_code == 200:
                break
        else:
            stderr_file.flush()
            detail = stderr_path.read_text(encoding="utf-8")
            raise RuntimeError(detail or "demo API did not start")
        yield base
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        stderr_file.close()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
