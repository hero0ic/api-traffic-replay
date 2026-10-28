import type { Diff, Outcome } from "./types";

export function formatWhen(value: string | null): string {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

export function outcomeLabel(outcome: Outcome): string {
  switch (outcome) {
    case "matched":
      return "Matched";
    case "regressed":
      return "Regressed";
    case "errored":
      return "Errored";
  }
}

export function formatDiffValue(value: unknown): string {
  if (value === undefined) {
    return "<missing>";
  }
  return JSON.stringify(value);
}

export function diffLabel(diff: Diff): string {
  return diff.path ? `${diff.kind} ${diff.path}` : diff.kind;
}

export function runStatus(run: {
  regressed: number;
  errored: number;
}): "clean" | "regressed" | "errored" {
  if (run.errored > 0) {
    return "errored";
  }
  if (run.regressed > 0) {
    return "regressed";
  }
  return "clean";
}
