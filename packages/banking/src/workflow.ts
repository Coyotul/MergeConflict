import type { Actor, ApplicationStatus, LoanApplication } from "./types";

export class DomainError extends Error {
  constructor(public code: string, message: string, public status = 400) { super(message); }
}
const transitions: Record<ApplicationStatus, ApplicationStatus[]> = {
  DRAFT: ["AWAITING_DOCUMENTS", "CANCELLED"], AWAITING_DOCUMENTS: ["READY_FOR_SUBMISSION", "CANCELLED"],
  READY_FOR_SUBMISSION: ["PENDING_HUMAN_REVIEW", "CANCELLED"],
  PENDING_HUMAN_REVIEW: ["MORE_INFORMATION_REQUIRED", "APPROVED", "REJECTED"],
  MORE_INFORMATION_REQUIRED: ["READY_FOR_SUBMISSION", "CANCELLED"], APPROVED: [], REJECTED: [], CANCELLED: [],
};
export function requireRole(actor: Actor, role: Actor["role"]) {
  if (actor.role !== role) throw new DomainError("FORBIDDEN", "Your demo role cannot perform this action.", 403);
}
export function requireAccess(actor: Actor, app: LoanApplication) {
  if (actor.role === "customer" ? app.customerId !== actor.id : app.reviewerId !== actor.id) {
    throw new DomainError("NOT_FOUND", "Application not found.", 404);
  }
}
export function hasRequiredDocuments(app: LoanApplication) {
  const kinds = ["identity", "income", ...(app.requestedDocument ? [app.requestedDocument] : [])];
  return kinds.every((kind) => app.documents.some((d) => d.kind === kind && d.status === "FORMAT_ACCEPTED"));
}
export function transition(app: LoanApplication, next: ApplicationStatus, actor: Actor, description: string) {
  if (!transitions[app.status].includes(next)) throw new DomainError("INVALID_TRANSITION", `Cannot change ${app.status} to ${next}.`, 409);
  app.status = next;
  app.updatedAt = new Date().toISOString();
  app.history.push({ id: crypto.randomUUID(), status: next, at: app.updatedAt, actor: actor.name, description });
}
export function assertSubmission(app: LoanApplication, actor: Actor, confirmed: boolean) {
  requireRole(actor, "customer"); requireAccess(actor, app);
  if (!confirmed) throw new DomainError("CONFIRMATION_REQUIRED", "Explicit submission confirmation is required.");
  if (app.status !== "READY_FOR_SUBMISSION" || !hasRequiredDocuments(app)) throw new DomainError("INVALID_TRANSITION", "Complete the requested documents before submitting.", 409);
}
export function assertReview(app: LoanApplication, actor: Actor, evidenceReviewed: boolean) {
  requireRole(actor, "reviewer"); requireAccess(actor, app);
  if (app.status !== "PENDING_HUMAN_REVIEW") throw new DomainError("INVALID_TRANSITION", "Only applications awaiting human review can receive a decision.", 409);
  if (!evidenceReviewed) throw new DomainError("EVIDENCE_REQUIRED", "Independently inspect the evidence before recording a decision.");
}
