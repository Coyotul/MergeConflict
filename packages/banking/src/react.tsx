"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import type { LoginCredentials, Role, Session, Snapshot } from "./types";
import { ApiError, endSession, getSnapshot, request, startSession } from "./api";
import { storedSessionSchema } from "./schemas";

interface DemoContextValue {
  snapshot: Snapshot | null; loading: boolean; busy: boolean; error: string | null;
  login: (credentials: LoginCredentials) => Promise<void>; refresh: () => Promise<void>; logout: () => Promise<void>;
  command: <T>(path: string, payload: unknown, method?: string) => Promise<T>;
  clearError: () => void;
}
const DemoContext = createContext<DemoContextValue | null>(null);
export function DemoProvider({ role, children }: { role: Role; children: ReactNode }) {
  const key = `luma-demo-session-v2-${role}`;
  const session = useRef<Session | null>(null);
  const authenticating = useRef(false);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const clearSession = useCallback(() => {
    session.current = null;
    sessionStorage.removeItem(key);
    setSnapshot(null);
  }, [key]);
  const refresh = useCallback(async () => {
    const current = session.current;
    if (!current) return;
    try {
      const next = await getSnapshot(current.token);
      if (session.current?.token !== current.token) return;
      setSnapshot(next); setError(null);
    }
    catch (e) {
      if (session.current?.token !== current.token) return;
      if (e instanceof ApiError && e.status === 401) clearSession();
      setError(e instanceof Error ? e.message : "Could not load demo data.");
    }
  }, [clearSession]);
  useEffect(() => {
    const stored = sessionStorage.getItem(key);
    if (stored) {
      try {
        const next = storedSessionSchema.parse(JSON.parse(stored));
        if (next.actor.role !== role || Date.parse(next.expiresAt) <= Date.now()) throw new Error("Expired or mismatched session.");
        session.current = next;
      } catch { sessionStorage.removeItem(key); }
    }
    let active = true;
    void refresh().finally(() => { if (active) setLoading(false); });
    const interval = setInterval(() => { if (document.visibilityState === "visible") void refresh(); }, 4000);
    const focus = () => { void refresh(); };
    window.addEventListener("focus", focus);
    return () => { active = false; clearInterval(interval); window.removeEventListener("focus", focus); };
  }, [key, role, refresh]);
  const login = useCallback(async (credentials: LoginCredentials) => {
    if (authenticating.current) return;
    authenticating.current = true;
    setLoading(true); setError(null);
    try {
      const next = await startSession(role, credentials);
      const initial = await getSnapshot(next.token);
      session.current = next;
      sessionStorage.setItem(key, JSON.stringify(next));
      setSnapshot(initial);
    }
    catch (e) { setError(e instanceof Error ? e.message : "Could not sign in to the demo."); }
    finally { authenticating.current = false; setLoading(false); }
  }, [key, role]);
  const logout = useCallback(async () => {
    const current = session.current;
    clearSession(); setError(null); setLoading(true);
    try { if (current) await endSession(current.token); }
    catch (e) {
      if (!(e instanceof ApiError && e.status === 401)) setError("Signed out on this device. The local service could not revoke the session; it will expire automatically.");
    }
    finally { setLoading(false); }
  }, [clearSession]);
  const command = useCallback(async <T,>(path: string, payload: unknown, method?: string): Promise<T> => {
    const current = session.current;
    if (!current) throw new Error("Sign in to your synthetic demo account first.");
    setBusy(true); setError(null);
    try { const result = await request<T>(path, current.token, payload, method); await refresh(); return result; }
    catch (e) {
      if (session.current?.token === current.token) {
        if (e instanceof ApiError && e.status === 401) clearSession();
        setError(e instanceof Error ? e.message : "The action failed.");
      }
      throw e;
    }
    finally { setBusy(false); }
  }, [refresh, clearSession]);
  return <DemoContext.Provider value={{ snapshot, loading, busy, error, login, logout, refresh, command, clearError: () => setError(null) }}>{children}</DemoContext.Provider>;
}
export function useDemo() {
  const value = useContext(DemoContext);
  if (!value) throw new Error("useDemo requires DemoProvider.");
  return value;
}
