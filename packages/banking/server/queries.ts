import type { Actor, DemoStore, Snapshot } from "../src/types";
import { interpretWithBedrock } from "./bedrock";
import { DomainError, requireRole } from "../src/workflow";
import { addAudit } from "./helpers";

export function snapshot(state: DemoStore, actor: Actor): Snapshot {
  const applications = state.applications.filter((app) => actor.role === "customer" ? app.customerId === actor.id : app.reviewerId === actor.id).map((app) => actor.role === "customer" ? { ...app, notes: app.notes.filter((n) => !n.internal) } : app);
  const customerId = actor.role === "customer" ? actor.id : applications[0]?.customerId;
  const customer = state.customers.find((c) => c.id === customerId);
  if (!customer) throw new DomainError("NOT_FOUND", "Demo customer profile not found.", 404);
  return { actor, customer, products: state.products, policies: state.policies, loans: state.loans.filter((l) => l.customerId === customerId), applications, messages: actor.role === "customer" ? state.messages[actor.id] ?? [] : [], notifications: actor.role === "customer" ? state.notifications.filter((n) => n.customerId === actor.id) : [], audit: state.audit.filter((a) => actor.role === "reviewer" ? applications.some((app) => app.id === a.objectId) : a.actorId === actor.id), consent: state.consents[customerId] ?? { financialInsights: false, notifications: false } };
}
export async function chat(state: DemoStore, actor: Actor, text: string) {
  requireRole(actor, "customer");
  const reply = await interpretWithBedrock(text, state, actor.id);
  const at = new Date().toISOString();
  const messages = state.messages[actor.id] ??= [];
  messages.push({ id: crypto.randomUUID(), at, role: "user", text, kind: "text" });
  const message = { id: crypto.randomUUID(), at, role: "assistant" as const, ...reply };
  messages.push(message);
  return message;
}
export function resetChat(state: DemoStore, actor: Actor) {
  requireRole(actor, "customer"); state.messages[actor.id] = [];
  addAudit(state, actor, "CONVERSATION_RESET", actor.id, "Application records retained");
  return { cleared: true };
}
export function requestSupport(state: DemoStore, actor: Actor, message: string) {
  requireRole(actor, "customer");
  const notification = { id: crypto.randomUUID(), customerId: actor.id, title: "Demo support request recorded", text: `${message} Conversation context is retained. No real representative has been contacted.`, at: new Date().toISOString(), read: false };
  state.notifications.unshift(notification);
  addAudit(state, actor, "SUPPORT_REQUESTED", actor.id, "Simulated handoff, no external contact");
  return notification;
}
