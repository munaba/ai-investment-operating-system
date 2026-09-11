import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { hasSession, login as apiLogin, logout as apiLogout } from '../api/client';

interface AuthState {
  isAuthed: boolean;
  loading: boolean;
  loginError: string | null;
  login: (username: string, password: string) => Promise<boolean>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

// Literal, compile-time in-app path. Navigation targets must NEVER be built
// from user input, URL params or server data.
const LOGIN_PATH = '/login';

// A root-relative path: starts with '/', is not protocol-relative ('//evil'),
// and carries no scheme/userinfo/port/query — i.e. it cannot escape the origin.
const SAFE_APP_PATH = /^\/(?!\/)[A-Za-z0-9._~\-/]*$/;

/**
 * Hardened in-app navigation (replaces window.location.assign).
 *
 * `location.assign(x)` accepts ANY absolute URL — including a `javascript:` /
 * `data:` URL or a protocol-relative `//attacker.example` — so any caller that
 * can reach it with dynamic text becomes an XSS / open-redirect sink. This
 * helper only ever accepts a validated root-relative path and refuses anything
 * else, so a future refactor that interpolates data fails closed instead of
 * navigating the operator off-site.
 */
export function navigateToAppPath(path: string): void {
  if (typeof window === 'undefined') return;
  if (!SAFE_APP_PATH.test(path)) {
    if (import.meta.env.DEV) {
      console.error(`[auth] refused unsafe navigation target: ${JSON.stringify(path)}`);
    }
    return;
  }
  window.location.href = path;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [isAuthed, setIsAuthed] = useState<boolean>(false);
  const [loading, setLoading] = useState(true);
  const [loginError, setLoginError] = useState<string | null>(null);

  useEffect(() => {
    hasSession().then((ok) => {
      setIsAuthed(ok);
      setLoading(false);
    });
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    setLoginError(null);
    try {
      await apiLogin(username, password);
      setIsAuthed(true);
      return true;
    } catch {
      // Login failed — server cookie not set. hasSession() will return false on next check.
      setIsAuthed(false);
      setLoginError('Username atau password salah.');
      return false;
    }
  }, []);

  const logout = useCallback(async () => {
    await apiLogout();
    setIsAuthed(false);
  }, []);

  const value = useMemo<AuthState>(
    () => ({ isAuthed, loading, loginError, login, logout }),
    [isAuthed, loading, loginError, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { isAuthed, loading } = useAuth();
  if (loading) return null; // wait for session check
  if (!isAuthed) {
    navigateToAppPath(LOGIN_PATH);
    return null;
  }
  return <>{children}</>;
}
