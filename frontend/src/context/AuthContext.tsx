import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { ApiError, api } from "../services/api";
import type { AccountUser, CustomerLogin, CustomerRegistration } from "../services/api";

const SESSION_KEY = "littleleaf-customer-session-v1";
const SESSION_EXPIRY_KEY = "littleleaf-customer-session-expiry-v1";

type AuthContextValue = {
  user: AccountUser | null;
  accessToken: string | null;
  isLoading: boolean;
  login: (credentials: CustomerLogin) => Promise<AccountUser>;
  register: (customer: CustomerRegistration) => Promise<AccountUser>;
  logout: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AccountUser | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [expiresAt, setExpiresAt] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    const token = window.sessionStorage.getItem(SESSION_KEY);
    const storedExpiry = Number(window.sessionStorage.getItem(SESSION_EXPIRY_KEY));
    if (!token || !Number.isFinite(storedExpiry) || storedExpiry <= Date.now()) {
      window.sessionStorage.removeItem(SESSION_KEY);
      window.sessionStorage.removeItem(SESSION_EXPIRY_KEY);
      setIsLoading(false);
      return () => { cancelled = true; };
    }

    api.currentUser(token)
      .then((account) => {
        if (!cancelled) {
          setUser(account);
          setAccessToken(token);
          setExpiresAt(storedExpiry);
        }
      })
      .catch((reason: unknown) => {
        if (reason instanceof ApiError && reason.status === 401) {
          window.sessionStorage.removeItem(SESSION_KEY);
          window.sessionStorage.removeItem(SESSION_EXPIRY_KEY);
          setAccessToken(null);
        }
      })
      .finally(() => { if (!cancelled) setIsLoading(false); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!expiresAt) return;
    const timeout = window.setTimeout(() => {
      window.sessionStorage.removeItem(SESSION_KEY);
      window.sessionStorage.removeItem(SESSION_EXPIRY_KEY);
      setUser(null);
      setAccessToken(null);
      setExpiresAt(null);
    }, Math.max(0, expiresAt - Date.now()));
    return () => window.clearTimeout(timeout);
  }, [expiresAt]);

  const login = useCallback(async (credentials: CustomerLogin) => {
    const session = await api.login(credentials);
    window.sessionStorage.setItem(SESSION_KEY, session.access_token);
    const sessionExpiry = Date.now() + session.expires_in * 1000;
    window.sessionStorage.setItem(SESSION_EXPIRY_KEY, String(sessionExpiry));
    setUser(session.user);
    setAccessToken(session.access_token);
    setExpiresAt(sessionExpiry);
    return session.user;
  }, []);

  const register = useCallback(async (customer: CustomerRegistration) => api.register(customer), []);

  const logout = useCallback(() => {
    window.sessionStorage.removeItem(SESSION_KEY);
    window.sessionStorage.removeItem(SESSION_EXPIRY_KEY);
    setUser(null);
    setAccessToken(null);
    setExpiresAt(null);
  }, []);

  const value = useMemo(() => ({ user, accessToken, isLoading, login, register, logout }), [user, accessToken, isLoading, login, register, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider.");
  return context;
}
