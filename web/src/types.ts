/** Types mirror the API report contract. The UI never re-diffs responses. */

export type Outcome = "matched" | "regressed" | "errored";
export type DiffKind = "status" | "header" | "json" | "body";
export type DiffOp = "replace" | "add" | "remove";

export interface Project {
  id: string;
  name: string;
  slug: string;
  created_at: string | null;
}

export interface RunSummary {
  id: string;
  project_id: string;
  collection_id: string | null;
  baseline_id: string | null;
  name: string;
  target: string | null;
  total: number;
  matched: number;
  regressed: number;
  errored: number;
  created_at: string | null;
}

export interface Diff {
  kind: DiffKind;
  path: string;
  op: DiffOp;
  baseline: unknown;
  candidate: unknown;
}

export interface CaseResult {
  id: string;
  method: string;
  path: string;
  outcome: Outcome;
  diffs: Diff[];
  error: string | null;
  baseline_status: number | null;
  candidate_status: number | null;
}

export interface Report {
  name: string;
  summary: {
    total: number;
    matched: number;
    regressed: number;
    errored: number;
  };
  results: CaseResult[];
}

export interface Diagnosis {
  id: string;
  run_id: string;
  provider: string;
  model: string;
  prompt_version: string;
  content: string;
  created_at: string | null;
}

export interface RunDetail extends RunSummary {
  report: Report;
  diagnosis: Diagnosis | null;
}
