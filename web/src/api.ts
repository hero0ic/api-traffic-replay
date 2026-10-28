import type { Diagnosis, Project, RunDetail, RunSummary } from "./types";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export async function fetchProject(projectId: string, token: string): Promise<Project> {
  return request<Project>(`/v1/projects/${projectId}`, token);
}

export async function fetchRuns(projectId: string, token: string): Promise<RunSummary[]> {
  return request<RunSummary[]>(`/v1/projects/${projectId}/runs`, token);
}

export async function fetchRun(
  projectId: string,
  runId: string,
  token: string,
): Promise<RunDetail> {
  return request<RunDetail>(`/v1/projects/${projectId}/runs/${runId}`, token);
}

export async function diagnoseRun(
  projectId: string,
  runId: string,
  token: string,
): Promise<Diagnosis> {
  return request<Diagnosis>(`/v1/projects/${projectId}/runs/${runId}/diagnose`, token, {
    method: "POST",
  });
}

async function request<T>(
  path: string,
  token: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/json",
      ...(init.headers ?? {}),
    },
  });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") {
        detail = body.detail;
      }
    } catch {
      // keep status text
    }
    throw new ApiError(detail, response.status);
  }
  return (await response.json()) as T;
}
