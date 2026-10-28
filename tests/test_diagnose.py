"""AI diagnosis narrates stored regressions; it does not decide pass/fail."""

import json

import pytest
from fastapi.testclient import TestClient

from replay_api.diagnose import (
    MAX_VALUE_CHARS,
    NoRegressionsError,
    build_diagnosis_prompt,
    extract_regressions,
)
from replay_api.llm import FakeProvider, set_provider_override

SAMPLE_REPORT = {
    "name": "demo",
    "summary": {"total": 2, "matched": 1, "regressed": 1, "errored": 0},
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
        },
        {
            "id": "clock",
            "method": "GET",
            "path": "/clock",
            "outcome": "matched",
            "diffs": [],
            "error": None,
            "baseline_status": 200,
            "candidate_status": 200,
        },
    ],
}


def _create_project(client: TestClient) -> dict:
    return client.post("/v1/projects", json={"name": "Demo"}).json()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _upload_run(client: TestClient, project: dict, report: dict) -> dict:
    response = client.post(
        f"/v1/projects/{project['id']}/runs",
        headers=_auth(project["token"]),
        json={"report": report, "target": "http://127.0.0.1:9/v2"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_extract_regressions_drops_matched() -> None:
    cases = extract_regressions(SAMPLE_REPORT)
    assert len(cases) == 1
    assert cases[0]["id"] == "health"
    assert cases[0]["diffs"][0]["kind"] == "status"


def test_build_prompt_truncates_long_values() -> None:
    long_value = "x" * 500
    report = {
        "name": "big",
        "summary": {"total": 1, "matched": 0, "regressed": 1, "errored": 0},
        "results": [
            {
                "id": "body",
                "method": "GET",
                "path": "/body",
                "outcome": "regressed",
                "diffs": [
                    {
                        "kind": "body",
                        "path": "",
                        "op": "replace",
                        "baseline": long_value,
                        "candidate": long_value,
                    }
                ],
            }
        ],
    }
    prompt = build_diagnosis_prompt(report)
    user = prompt["messages"][1]["content"]
    payload = json.loads(user)
    baseline = payload["regressions"][0]["diffs"][0]["baseline"]
    assert isinstance(baseline, str)
    assert len(baseline) == MAX_VALUE_CHARS
    assert baseline.endswith("…")


def test_build_prompt_rejects_empty_regressions() -> None:
    report = {
        "name": "clean",
        "summary": {"total": 1, "matched": 1, "regressed": 0, "errored": 0},
        "results": [
            {
                "id": "ok",
                "method": "GET",
                "path": "/",
                "outcome": "matched",
                "diffs": [],
            }
        ],
    }
    with pytest.raises(NoRegressionsError):
        build_diagnosis_prompt(report)


def test_diagnose_disabled_without_provider(api_client: TestClient) -> None:
    project = _create_project(api_client)
    run = _upload_run(api_client, project, SAMPLE_REPORT)
    response = api_client.post(
        f"/v1/projects/{project['id']}/runs/{run['id']}/diagnose",
        headers=_auth(project["token"]),
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "AI diagnosis is disabled on this server"


def test_diagnose_stores_and_replaces(api_client: TestClient) -> None:
    project = _create_project(api_client)
    run = _upload_run(api_client, project, SAMPLE_REPORT)
    assert run["diagnosis"] is None

    first = FakeProvider("First explanation about status 500.")
    set_provider_override(first)
    created = api_client.post(
        f"/v1/projects/{project['id']}/runs/{run['id']}/diagnose",
        headers=_auth(project["token"]),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["content"] == "First explanation about status 500."
    assert body["provider"] == "fake"
    assert body["prompt_version"] == "v1"
    assert len(first.calls) == 1
    user_payload = json.loads(first.calls[0][1]["content"])
    assert user_payload["regressions"][0]["id"] == "health"
    assert all(case["id"] != "clock" for case in user_payload["regressions"])

    detail = api_client.get(
        f"/v1/projects/{project['id']}/runs/{run['id']}",
        headers=_auth(project["token"]),
    )
    assert detail.status_code == 200
    assert detail.json()["diagnosis"]["content"].startswith("First explanation")

    second = FakeProvider("Updated explanation.")
    set_provider_override(second)
    replaced = api_client.post(
        f"/v1/projects/{project['id']}/runs/{run['id']}/diagnose",
        headers=_auth(project["token"]),
    )
    assert replaced.status_code == 201
    assert replaced.json()["content"] == "Updated explanation."

    fetched = api_client.get(
        f"/v1/projects/{project['id']}/runs/{run['id']}/diagnosis",
        headers=_auth(project["token"]),
    )
    assert fetched.status_code == 200
    assert fetched.json()["content"] == "Updated explanation."


def test_diagnose_rejects_clean_run(api_client: TestClient) -> None:
    project = _create_project(api_client)
    clean = {
        "name": "clean",
        "summary": {"total": 1, "matched": 1, "regressed": 0, "errored": 0},
        "results": [
            {
                "id": "ok",
                "method": "GET",
                "path": "/",
                "outcome": "matched",
                "diffs": [],
                "error": None,
                "baseline_status": 200,
                "candidate_status": 200,
            }
        ],
    }
    run = _upload_run(api_client, project, clean)
    set_provider_override(FakeProvider())
    response = api_client.post(
        f"/v1/projects/{project['id']}/runs/{run['id']}/diagnose",
        headers=_auth(project["token"]),
    )
    assert response.status_code == 400
    assert "no regressions" in response.json()["detail"]
