import { createHash } from "node:crypto";
import type { Actor, DemoStore, LoanApplication } from "../src/types";
import { DomainError, requireAccess } from "../src/workflow";

export function applicationFor(state: DemoStore, actor: Actor, id: string): LoanApplication {
  const app = state.applications.find((a) => a.id === id);
  if (!app) throw new DomainError("NOT_FOUND", "Application not found.", 404);
  requireAccess(actor, app);
  return app;
}
export function addAudit(state: DemoStore, actor: Actor, action: string, objectId: string, result: string) {
  state.audit.push({ id: crypto.randomUUID(), actorId: actor.id, actor: actor.name, action, objectId, result, at: new Date().toISOString() });
}
export function notify(state: DemoStore, app: LoanApplication, title: string, text: string) {
  state.notifications.unshift({ id: crypto.randomUUID(), customerId: app.customerId, title, text, at: new Date().toISOString(), read: false, applicationId: app.id });
}
export function idempotent(state: DemoStore, actor: Actor, key: string, operation: string, payload: unknown, fn: () => LoanApplication) {
  const fingerprint = createHash("sha256").update(JSON.stringify({ operation, payload })).digest("hex");
  const existing = state.idempotency.find((r) => r.actorId === actor.id && r.key === key);
  if (existing) {
    if (existing.fingerprint !== fingerprint) throw new DomainError("IDEMPOTENCY_CONFLICT", "This request key was already used with different inputs.", 409);
    return applicationFor(state, actor, existing.applicationId);
  }
  const result = fn();
  state.idempotency.push({ actorId: actor.id, key, fingerprint, applicationId: result.id });
  return result;
}
