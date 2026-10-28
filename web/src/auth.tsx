import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { fetchProject } from "./api";
import type { Project } from "./types";

const STORAGE_KEY = "replay.session";

interface Session {
  projectId: string;
  token: string;
  project: Project;
}

interface AuthContextValue {
  session: Session | null;
  login: (projectId: string, token: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function loadStored(): { projectId: string; token: string } | null {
  const raw = sessionStorage.getItem(STORAGE_KEY);
  if (!raw) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw) as { projectId?: string; token?: string };
    if (parsed.projectId && parsed.token) {
      return { projectId: parsed.projectId, token: parsed.token };
    }
  } catch {
    sessionStorage.removeItem(STORAGE_KEY);
  }
  return null;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [bootstrapped, setBootstrapped] = useState(() => loadStored() === null);

  useEffect(() => {
    const stored = loadStored();
    if (!stored) {
      setBootstrapped(true);
      return;
    }
    let cancelled = false;
    fetchProject(stored.projectId, stored.token)
      .then((project) => {
        if (!cancelled) {
          setSession({
            projectId: stored.projectId,
            token: stored.token,
            project,
          });
          setBootstrapped(true);
        }
      })
      .catch(() => {
        if (!cancelled) {
          sessionStorage.removeItem(STORAGE_KEY);
          setBootstrapped(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (projectId: string, token: string) => {
    const project = await fetchProject(projectId.trim(), token.trim());
    const next = { projectId: project.id, token: token.trim(), project };
    sessionStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ projectId: next.projectId, token: next.token }),
    );
    setSession(next);
  }, []);

  const logout = useCallback(() => {
    sessionStorage.removeItem(STORAGE_KEY);
    setSession(null);
  }, []);

  const value = useMemo(() => ({ session, login, logout }), [session, login, logout]);

  if (!bootstrapped) {
    return <div className="page muted">Restoring session…</div>;
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return value;
}
