import type { LoginCredentials, Session, Role, Snapshot } from "./types";

export class ApiError extends Error {
  constructor(message: string, public status: number, public code: string) { super(message); }
}
const base = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:4010/api";
export async function request<T>(path: string, token?: string, payload?: unknown, method?: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${base}${path}`, { method: method ?? (payload === undefined ? "GET" : "POST"), headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) }, ...(payload !== undefined ? { body: JSON.stringify(payload) } : {}), signal: AbortSignal.timeout(10000), cache: "no-store" });
  } catch { throw new ApiError("The local demo API is unavailable. Start all three services with npm run dev, then retry.", 0, "SERVICE_UNAVAILABLE"); }
  const result = await response.json();
  if (!response.ok) throw new ApiError(result.error?.message ?? "The request failed.", response.status, result.error?.code ?? "REQUEST_FAILED");
  return result.data as T;
}
export const startSession = (role: Role, credentials: LoginCredentials) => request<Session>("/session", undefined, { ...credentials, role });
export const endSession = (token: string) => request<{ signedOut: boolean }>("/session/logout", token, {});
export const getSnapshot = (token: string) => request<Snapshot>("/snapshot", token);
