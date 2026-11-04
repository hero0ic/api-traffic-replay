"""CLI upload helpers store the same report JSON the API already accepts."""

import json
import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from replay_core.client import ApiError, ReplayApiClient, _error_detail
from replay_core.loader import load_report, load_requests
from replay_core.models import Report

ROOT = Path(__file__).resolve().parents[1]

SAMPLE_REPORT = {
    "name": "demo",
    "summary": {"total": 1, "matched": 0, "regressed": 1, "errored": 0},
    "results": [
        {
            "id": "health",
            "method": "GET",
            "path": "/health",
            "outcome": "regressed",
            "diffs": [
                {"kind": "status", "path": "", "op": "replace", "baseline": 200, "candidate": 500}
            ],
            "error": None,
            "baseline_status": 200,
            "candidate_status": 500,
        }
    ],
}


def test_client_upload_round_trip(api_client: TestClient) -> None:
    created = api_client.post("/v1/projects", json={"name": "CLI"}).json()
    client = _client_over_testclient(api_client, created["token"])
    report = Report.model_validate(SAMPLE_REPORT)
    uploaded = client.upload_run(created["id"], report, target="http://example.test/v2")
    assert uploaded["regressed"] == 1
    assert uploaded["report"]["name"] == "demo"


def test_upload_collection_then_run(api_client: TestClient, tmp_path: Path) -> None:
    created = api_client.post("/v1/projects", json={"name": "Files"}).json()
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(SAMPLE_REPORT), encoding="utf-8")
    requests_path = tmp_path / "requests.json"
    requests_path.write_text(
        json.dumps(
            {
                "name": "demo",
                "requests": [{"id": "health", "method": "GET", "path": "/health"}],
            }
        ),
        encoding="utf-8",
    )
    client = _client_over_testclient(api_client, created["token"])
    collection = client.upload_collection(created["id"], load_requests(requests_path))
    run = client.upload_run(
        created["id"],
        load_report(report_path),
        collection_id=collection["id"],
        target="http://127.0.0.1:9/v2",
    )
    assert run["collection_id"] == collection["id"]
    assert run["report"]["summary"] == SAMPLE_REPORT["summary"]
    assert run["report"]["results"][0]["id"] == "health"


def test_projects_create_help() -> None:
    result = _run_cli(["projects", "create", "--help"])
    assert result.returncode == 0
    assert "--name" in result.stdout
    assert "--api-url" in result.stdout


def test_upload_help() -> None:
    result = _run_cli(["upload", "--help"])
    assert result.returncode == 0
    assert "--report" in result.stdout
    assert "--token" in result.stdout


def test_diagnose_help() -> None:
    result = _run_cli(["diagnose", "--help"])
    assert result.returncode == 0
    assert "--run-id" in result.stdout
    assert "--project-id" in result.stdout


def _run_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "replay_core.cli", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _client_over_testclient(api_client: TestClient, token: str) -> ReplayApiClient:
    client = ReplayApiClient("http://test", token=token)

    def request(method: str, path: str, *, json=None, auth: bool = False):
        headers = {"Authorization": f"Bearer {token}"} if auth else {}
        response = api_client.request(method, path, json=json, headers=headers)
        if response.status_code >= 400:
            raise ApiError(_error_detail(response), status_code=response.status_code)
        return response.json()

    client._request = request  # type: ignore[method-assign]
    return client
