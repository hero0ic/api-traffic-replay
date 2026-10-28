"""Hosted API stores the report the engine already produced."""

from fastapi.testclient import TestClient


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


def _create_project(client: TestClient, name: str = "Demo") -> dict:
    response = client.post("/v1/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_health(api_client: TestClient) -> None:
    assert api_client.get("/health").json() == {"status": "ok"}


def test_create_project_returns_token_once(api_client: TestClient) -> None:
    created = _create_project(api_client)
    assert created["name"] == "Demo"
    assert created["token"]
    assert "token_hash" not in created

    listed = api_client.get(f"/v1/projects/{created['id']}", headers=_auth(created["token"]))
    assert listed.status_code == 200
    body = listed.json()
    assert body["id"] == created["id"]
    assert "token" not in body


def test_invalid_token_is_rejected(api_client: TestClient) -> None:
    created = _create_project(api_client)
    response = api_client.get(f"/v1/projects/{created['id']}", headers=_auth("wrong-token"))
    assert response.status_code == 401


def test_upload_collection_baseline_and_run(api_client: TestClient) -> None:
    created = _create_project(api_client)
    headers = _auth(created["token"])
    project_id = created["id"]

    collection = api_client.post(
        f"/v1/projects/{project_id}/collections",
        headers=headers,
        json={
            "name": "demo",
            "ignore": ["created_at"],
            "requests": [{"id": "health", "method": "GET", "path": "/health"}],
        },
    )
    assert collection.status_code == 201, collection.text
    collection_id = collection.json()["id"]

    baseline = api_client.post(
        f"/v1/projects/{project_id}/baselines",
        headers=headers,
        json={
            "collection_id": collection_id,
            "baseline": {
                "name": "demo",
                "target": "http://127.0.0.1:8001/v1",
                "exchanges": [
                    {
                        "id": "health",
                        "method": "GET",
                        "path": "/health",
                        "status": 200,
                        "headers": {"content-type": "application/json"},
                        "json": {"status": "ok"},
                        "is_json": True,
                    }
                ],
            },
        },
    )
    assert baseline.status_code == 201, baseline.text
    baseline_id = baseline.json()["id"]

    run = api_client.post(
        f"/v1/projects/{project_id}/runs",
        headers=headers,
        json={
            "report": SAMPLE_REPORT,
            "target": "http://127.0.0.1:8001/v2",
            "collection_id": collection_id,
            "baseline_id": baseline_id,
        },
    )
    assert run.status_code == 201, run.text
    body = run.json()
    assert body["total"] == 2
    assert body["regressed"] == 1
    assert body["report"] == SAMPLE_REPORT
    assert body["collection_id"] == collection_id
    assert body["baseline_id"] == baseline_id

    listed = api_client.get(f"/v1/projects/{project_id}/runs", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["id"] == body["id"]

    detail = api_client.get(f"/v1/projects/{project_id}/runs/{body['id']}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["report"]["results"][0]["diffs"][0]["kind"] == "status"


def test_run_rejects_foreign_collection(api_client: TestClient) -> None:
    first = _create_project(api_client, "One")
    second = _create_project(api_client, "Two")
    collection = api_client.post(
        f"/v1/projects/{first['id']}/collections",
        headers=_auth(first["token"]),
        json={"name": "demo", "requests": [{"id": "a", "method": "GET", "path": "/"}]},
    )
    assert collection.status_code == 201

    response = api_client.post(
        f"/v1/projects/{second['id']}/runs",
        headers=_auth(second["token"]),
        json={"report": SAMPLE_REPORT, "collection_id": collection.json()["id"]},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "collection not found"
