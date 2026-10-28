import { diffLabel, formatDiffValue, outcomeLabel } from "../format";
import type { CaseResult, Report } from "../types";

interface Props {
  report: Report;
  showMatched: boolean;
}

export function DiffList({ report, showMatched }: Props) {
  const results = showMatched
    ? report.results
    : report.results.filter((result) => result.outcome !== "matched");

  if (results.length === 0) {
    return <p className="muted">Every request matched the baseline.</p>;
  }

  return (
    <div className="result-list">
      {results.map((result) => (
        <ResultCard key={result.id} result={result} />
      ))}
    </div>
  );
}

function ResultCard({ result }: { result: CaseResult }) {
  return (
    <article className={`result-card outcome-${result.outcome}`}>
      <header className="result-header">
        <span className={`outcome-tag outcome-${result.outcome}`}>
          {outcomeLabel(result.outcome)}
        </span>
        <code className="request-id">{result.id}</code>
        <span className="request-line">
          {result.method} {result.path}
        </span>
        <span className="status-pair muted">
          {result.baseline_status ?? "—"} → {result.candidate_status ?? "—"}
        </span>
      </header>
      {result.error ? <p className="error-line">{result.error}</p> : null}
      {result.diffs.length > 0 ? (
        <table className="diff-table">
          <thead>
            <tr>
              <th>Change</th>
              <th>Op</th>
              <th>Baseline</th>
              <th>Candidate</th>
            </tr>
          </thead>
          <tbody>
            {result.diffs.map((diff, index) => (
              <tr key={`${diff.kind}-${diff.path}-${diff.op}-${index}`}>
                <td>
                  <code>{diffLabel(diff)}</code>
                </td>
                <td>{diff.op}</td>
                <td>
                  <code>{formatDiffValue(diff.op === "add" ? undefined : diff.baseline)}</code>
                </td>
                <td>
                  <code>{formatDiffValue(diff.op === "remove" ? undefined : diff.candidate)}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </article>
  );
}
