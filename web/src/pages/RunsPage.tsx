import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError, fetchRuns } from "../api";
import { useAuth } from "../auth";
import { SummaryPills } from "../components/SummaryPills";
import { formatWhen, runStatus } from "../format";
import type { RunSummary } from "../types";

export function RunsPage() {
  const { session, logout } = useAuth();
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!session) {
      return;
    }
    let cancelled = false;
    fetchRuns(session.projectId, session.token)
      .then((data) => {
        if (!cancelled) {
          setRuns(data);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "Failed to load runs");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [session]);

  if (!session) {
    return null;
  }

  return (
    <div className="page">
      <header className="topbar">
        <div>
          <p className="eyebrow">API Traffic Replay</p>
          <h1>{session.project.name}</h1>
          <p className="muted mono">{session.project.slug}</p>
        </div>
        <button type="button" className="ghost" onClick={logout}>
          Sign out
        </button>
      </header>

      <section className="panel">
        <div className="panel-head">
          <h2>Runs</h2>
          <p className="muted">Uploaded by the CLI. Open a run to inspect stored diffs.</p>
        </div>
        {error ? <p className="form-error">{error}</p> : null}
        {runs === null && !error ? <p className="muted">Loading runs…</p> : null}
        {runs && runs.length === 0 ? (
          <p className="muted">
            No runs yet. Upload one with <code>replay upload</code>.
          </p>
        ) : null}
        {runs && runs.length > 0 ? (
          <div className="run-table-wrap">
            <table className="run-table">
              <thead>
                <tr>
                  <th>Status</th>
                  <th>Name</th>
                  <th>Summary</th>
                  <th>Target</th>
                  <th>When</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.id}>
                    <td>
                      <span className={`status-dot status-${runStatus(run)}`}>
                        {runStatus(run)}
                      </span>
                    </td>
                    <td>
                      <Link to={`/runs/${run.id}`}>{run.name}</Link>
                    </td>
                    <td>
                      <SummaryPills
                        total={run.total}
                        matched={run.matched}
                        regressed={run.regressed}
                        errored={run.errored}
                      />
                    </td>
                    <td className="mono muted">{run.target ?? "—"}</td>
                    <td className="muted">{formatWhen(run.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
    </div>
  );
}
