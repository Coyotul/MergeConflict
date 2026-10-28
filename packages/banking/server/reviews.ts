import type { Actor, DemoStore } from "../src/types";
import type { ReviewInput } from "../src/schemas";
import { assertReview, DomainError, hasRequiredDocuments, requireRole, transition } from "../src/workflow";
import { documentLabels } from "../src/format";
import { addAudit, applicationFor, idempotent, notify } from "./helpers";

export function reviewApplication(state: DemoStore, actor: Actor, id: string, input: ReviewInput) {
  requireRole(actor, "reviewer");
  const { idempotencyKey, ...payload } = input;
  return idempotent(state, actor, idempotencyKey, `review:${id}`, payload, () => {
    const app = applicationFor(state, actor, id);
    assertReview(app, actor, input.evidenceReviewed);
    if (input.action !== "request-information" && !hasRequiredDocuments(app)) throw new DomainError("EVIDENCE_REQUIRED", "Required demo document metadata is incomplete.", 409);
    const next = input.action === "approve" ? "APPROVED" : input.action === "reject" ? "REJECTED" : "MORE_INFORMATION_REQUIRED";
    if (input.action === "request-information") {
      app.requestedDocument = input.requestedDocument;
      app.requestReason = input.reason;
      const document = app.documents.find((d) => d.kind === input.requestedDocument)!;
      document.status = "MISSING";
    } else { app.decisionReason = input.reason; }
    transition(app, next, actor, input.reason);
    app.notes.push({ id: crypto.randomUUID(), author: actor.name, at: app.updatedAt, text: input.reason, internal: false });
    addAudit(state, actor, `REVIEW_${input.action.toUpperCase().replaceAll("-", "_")}`, id, `Synthetic human decision: ${input.reason}`);
    notify(state, app, input.action === "request-information" ? "A reviewer needs more information" : "Your demo review has an outcome", input.action === "request-information" ? `${documentLabels[input.requestedDocument!]} requested: ${input.reason}` : `${input.reason} This is a synthetic review only; nothing was signed or funded.`);
    return app;
  });
}
export function addNote(state: DemoStore, actor: Actor, id: string, text: string) {
  requireRole(actor, "reviewer");
  const app = applicationFor(state, actor, id);
  app.notes.push({ id: crypto.randomUUID(), author: actor.name, at: new Date().toISOString(), text, internal: true });
  addAudit(state, actor, "INTERNAL_NOTE_ADDED", id, "Recorded for assigned reviewer only");
  return app;
}
