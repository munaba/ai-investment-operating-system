import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { clearSession, hasSession, login as apiLogin, logout as apiLogout } from '../api/client';

interface AuthState {
  isAuthed: boolean;
  loading: boolean;
  loginError: string | null;
  login: (username: string, password: string) => Promise<boolean>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

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
      clearSession();
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
    [isAuthed, loading, loginError],
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
  if (loading) return null;
  if (!isAuthed) {
    if (typeof window !== 'undefined') window.location.assign('/login');
    return null;
  }
  return <>{children}</>;
}
