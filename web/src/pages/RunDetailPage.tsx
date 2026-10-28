import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ApiError, diagnoseRun, fetchRun } from "../api";
import { useAuth } from "../auth";
import { DiffList } from "../components/DiffList";
import { SummaryPills } from "../components/SummaryPills";
import { formatWhen, runStatus } from "../format";
import type { Diagnosis, RunDetail } from "../types";

export function RunDetailPage() {
  const { runId = "" } = useParams();
  const { session, logout } = useAuth();
  const [run, setRun] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showMatched, setShowMatched] = useState(false);
  const [diagnosis, setDiagnosis] = useState<Diagnosis | null>(null);
  const [diagnoseError, setDiagnoseError] = useState<string | null>(null);
  const [diagnosing, setDiagnosing] = useState(false);

  useEffect(() => {
    if (!session || !runId) {
      return;
    }
    let cancelled = false;
    fetchRun(session.projectId, runId, session.token)
      .then((data) => {
        if (!cancelled) {
          setRun(data);
          setDiagnosis(data.diagnosis);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "Failed to load run");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [session, runId]);

  async function onDiagnose() {
    if (!session || !runId) {
      return;
    }
    setDiagnoseError(null);
    setDiagnosing(true);
    try {
      const result = await diagnoseRun(session.projectId, runId, session.token);
      setDiagnosis(result);
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 503) {
        setDiagnoseError("AI diagnosis is disabled on this server");
      } else if (err instanceof ApiError) {
        setDiagnoseError(err.message);
      } else {
        setDiagnoseError("Failed to request diagnosis");
      }
    } finally {
      setDiagnosing(false);
    }
  }

  if (!session) {
    return null;
  }

  return (
    <div className="page">
      <header className="topbar">
        <div>
          <p className="eyebrow">
            <Link to="/runs">← Runs</Link>
          </p>
          <h1>{run?.name ?? "Run"}</h1>
          <p className="muted">{run ? formatWhen(run.created_at) : "Loading…"}</p>
        </div>
        <button type="button" className="ghost" onClick={logout}>
          Sign out
        </button>
      </header>

      {error ? <p className="form-error">{error}</p> : null}
      {!run && !error ? <p className="muted">Loading report…</p> : null}

      {run ? (
        <>
          <section className="panel">
            <div className="panel-head row">
              <div>
                <h2>Summary</h2>
                <p className="muted">
                  Stored counts from the engine. Status:{" "}
                  <span className={`status-dot status-${runStatus(run)}`}>{runStatus(run)}</span>
                </p>
              </div>
              <SummaryPills
                total={run.total}
                matched={run.matched}
                regressed={run.regressed}
                errored={run.errored}
              />
            </div>
            <dl className="meta-grid">
              <div>
                <dt>Target</dt>
                <dd className="mono">{run.target ?? "—"}</dd>
              </div>
              <div>
                <dt>Run ID</dt>
                <dd className="mono">{run.id}</dd>
              </div>
            </dl>
          </section>

          <section className="panel">
            <div className="panel-head row">
              <div>
                <h2>AI diagnosis</h2>
                <p className="muted">
                  Explains already-detected regressions. The model does not decide pass or fail.
                </p>
              </div>
              <button
                type="button"
                className="ghost"
                disabled={run.regressed === 0 || diagnosing}
                onClick={() => void onDiagnose()}
              >
                {diagnosing ? "Explaining…" : diagnosis ? "Regenerate" : "Explain regressions"}
              </button>
            </div>
            {run.regressed === 0 ? (
              <p className="muted">No regressions in this run to explain.</p>
            ) : null}
            {diagnoseError ? <p className="form-error">{diagnoseError}</p> : null}
            {diagnosis ? (
              <div className="diagnosis-block">
                <p className="muted diagnosis-meta">
                  {diagnosis.provider} / {diagnosis.model} · prompt {diagnosis.prompt_version} ·{" "}
                  {formatWhen(diagnosis.created_at)}
                </p>
                <pre className="diagnosis-content">{diagnosis.content}</pre>
              </div>
            ) : null}
          </section>

          <section className="panel">
            <div className="panel-head row">
              <div>
                <h2>Diffs</h2>
                <p className="muted">
                  Rendered from <code>report.results</code>. No second comparison happens here.
                </p>
              </div>
              <label className="toggle">
                <input
                  type="checkbox"
                  checked={showMatched}
                  onChange={(event) => setShowMatched(event.target.checked)}
                />
                Show matched
              </label>
            </div>
            <DiffList report={run.report} showMatched={showMatched} />
          </section>
        </>
      ) : null}
    </div>
  );
}
