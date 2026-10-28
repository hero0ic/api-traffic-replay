"""HTTP client for uploading local replay artifacts to the hosted API."""

from typing import Any
from uuid import UUID

import httpx

from replay_core.models import Baseline, Report, RequestCollection


class ApiError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)


class ReplayApiClient:
    def __init__(self, base_url: str, token: str | None = None, *, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def create_project(self, name: str) -> dict[str, Any]:
        return self._request("POST", "/v1/projects", json={"name": name})

    def upload_collection(self, project_id: UUID | str, collection: RequestCollection) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/projects/{project_id}/collections",
            json=collection.model_dump(mode="json", by_alias=True),
            auth=True,
        )

    def upload_baseline(
        self,
        project_id: UUID | str,
        baseline: Baseline,
        *,
        collection_id: UUID | str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"baseline": baseline.model_dump(mode="json", by_alias=True)}
        if collection_id is not None:
            body["collection_id"] = str(collection_id)
        return self._request(
            "POST",
            f"/v1/projects/{project_id}/baselines",
            json=body,
            auth=True,
        )

    def upload_run(
        self,
        project_id: UUID | str,
        report: Report,
        *,
        target: str | None = None,
        collection_id: UUID | str | None = None,
        baseline_id: UUID | str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"report": report.model_dump(mode="json", by_alias=True)}
        if target is not None:
            body["target"] = target
        if collection_id is not None:
            body["collection_id"] = str(collection_id)
        if baseline_id is not None:
            body["baseline_id"] = str(baseline_id)
        return self._request(
            "POST",
            f"/v1/projects/{project_id}/runs",
            json=body,
            auth=True,
        )

    def diagnose_run(self, project_id: UUID | str, run_id: UUID | str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/projects/{project_id}/runs/{run_id}/diagnose",
            auth=True,
        )

    def get_diagnosis(self, project_id: UUID | str, run_id: UUID | str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/v1/projects/{project_id}/runs/{run_id}/diagnosis",
            auth=True,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        auth: bool = False,
    ) -> dict[str, Any]:
        headers: dict[str, str] = {}
        if auth:
            if not self.token:
                raise ApiError("API token is required for this request")
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            response = httpx.request(
                method,
                f"{self.base_url}{path}",
                json=json,
                headers=headers,
                timeout=self.timeout,
                trust_env=False,
            )
        except httpx.HTTPError as exc:
            raise ApiError(f"request failed: {exc}") from exc
        if response.status_code >= 400:
            detail = _error_detail(response)
            raise ApiError(detail, status_code=response.status_code)
        return response.json()


def _error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        return text or f"HTTP {response.status_code}"
    if isinstance(payload, dict) and "detail" in payload:
        detail = payload["detail"]
        if isinstance(detail, str):
            return detail
        return str(detail)
    return f"HTTP {response.status_code}"
