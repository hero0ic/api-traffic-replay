import { useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";

import { ApiError } from "../api";
import { useAuth } from "../auth";

export function LoginPage() {
  const { session, login } = useAuth();
  const [projectId, setProjectId] = useState("");
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  if (session) {
    return <Navigate to="/runs" replace />;
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setPending(true);
    try {
      await login(projectId, token);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Could not reach the API. Is it running on port 8000?");
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="page login-page">
      <div className="login-panel">
        <p className="eyebrow">API Traffic Replay</p>
        <h1>Open a project</h1>
        <p className="lede">
          Paste the project id and token from <code>replay projects create</code>. The dashboard
          only reads stored reports; it does not replay or compare HTTP itself.
        </p>
        <form className="stack" onSubmit={onSubmit}>
          <label className="field">
            <span>Project ID</span>
            <input
              value={projectId}
              onChange={(event) => setProjectId(event.target.value)}
              autoComplete="off"
              spellCheck={false}
              required
            />
          </label>
          <label className="field">
            <span>API token</span>
            <input
              type="password"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              autoComplete="off"
              required
            />
          </label>
          {error ? <p className="form-error">{error}</p> : null}
          <button type="submit" disabled={pending}>
            {pending ? "Checking…" : "Open dashboard"}
          </button>
        </form>
      </div>
    </div>
  );
}
