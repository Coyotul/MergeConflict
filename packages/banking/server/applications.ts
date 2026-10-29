import type { Actor, DemoStore, LoanApplication } from "../src/types";
import type { CreateApplicationInput, SubmitInput, UploadInput } from "../src/schemas";
import { assessAffordability, calculateLoan, sumMoney } from "../src/finance";
import { documentLabels } from "../src/format";
import { assertSubmission, DomainError, hasRequiredDocuments, requireRole, transition } from "../src/workflow";
import { addAudit, applicationFor, idempotent, notify } from "./helpers";

export function createApplication(state: DemoStore, actor: Actor, input: CreateApplicationInput) {
  requireRole(actor, "customer");
  const { idempotencyKey, ...payload } = input;
  return idempotent(state, actor, idempotencyKey, "create", payload, () => {
    const product = state.products.find((p) => p.id === input.productId);
    const customer = state.customers.find((c) => c.id === actor.id);
    if (!product || !customer) throw new DomainError("NOT_FOUND", "Demo product or customer not found.", 404);
    if (Number(input.amount) < Number(product.minAmount) || Number(input.amount) > Number(product.maxAmount) || input.months < product.minMonths || input.months > product.maxMonths) throw new DomainError("VALIDATION_ERROR", "Amount or duration is outside this demo product's range.");
    const quote = calculateLoan(input.amount, product.annualRate, input.months, product.fee, product.monthlyInsurance);
    const obligations = sumMoney(state.loans.filter((l) => l.customerId === actor.id).map((l) => calculateLoan(l.principal, l.annualRate, l.remainingMonths).monthlyPayment));
    const now = new Date().toISOString();
    const app: LoanApplication = { id: crypto.randomUUID(), reference: `LM-${1000 + state.applications.length + 1}`, customerId: actor.id, customer, reviewerId: "reviewer-jamie", productId: product.id, policyVersion: "DEMO-2026.1", amount: quote.amount, months: input.months, quote, assessment: assessAffordability(customer.monthlyIncome, obligations, quote), status: "DRAFT", createdAt: now, updatedAt: now, documents: [{ kind: "identity", status: "MISSING" }, { kind: "income", status: "MISSING" }, { kind: "statement", status: "MISSING" }], history: [{ id: crypto.randomUUID(), status: "DRAFT", at: now, actor: actor.name, description: "Customer saved an indicative scenario. Not submitted." }], notes: [] };
    transition(app, "AWAITING_DOCUMENTS", actor, "Add synthetic identity and income document metadata.");
    state.applications.unshift(app);
    addAudit(state, actor, "APPLICATION_CREATED", app.id, "Synthetic draft only");
    return app;
  });
}
export function uploadDocument(state: DemoStore, actor: Actor, id: string, input: UploadInput) {
  requireRole(actor, "customer");
  const app = applicationFor(state, actor, id);
  if (!["AWAITING_DOCUMENTS", "MORE_INFORMATION_REQUIRED", "READY_FOR_SUBMISSION"].includes(app.status)) throw new DomainError("INVALID_TRANSITION", "This application is not accepting document metadata.", 409);
  const document = app.documents.find((d) => d.kind === input.kind)!;
  Object.assign(document, { status: "FORMAT_ACCEPTED", name: input.name, mimeType: input.mimeType, size: input.size, uploadedAt: new Date().toISOString() });
  app.updatedAt = new Date().toISOString();
  addAudit(state, actor, "DOCUMENT_METADATA_ADDED", app.id, `${input.kind}: format accepted, not authenticity verified`);
  if (app.status !== "READY_FOR_SUBMISSION" && hasRequiredDocuments(app)) transition(app, "READY_FOR_SUBMISSION", actor, "Demo checklist complete. Explicit customer submission is still required.");
  app.notes.push({ id: crypto.randomUUID(), author: actor.name, at: app.updatedAt, text: `${documentLabels[input.kind]} metadata added. No bytes uploaded or OCR performed.`, internal: false });
  return app;
}
export function submitApplication(state: DemoStore, actor: Actor, id: string, input: SubmitInput) {
  requireRole(actor, "customer");
  return idempotent(state, actor, input.idempotencyKey, `submit:${id}`, { confirmed: input.confirmed }, () => {
    const app = applicationFor(state, actor, id);
    assertSubmission(app, actor, input.confirmed);
    transition(app, "PENDING_HUMAN_REVIEW", actor, "Customer explicitly confirmed submission to an independent demo reviewer.");
    app.requestedDocument = undefined;
    app.requestReason = undefined;
    addAudit(state, actor, "APPLICATION_SUBMITTED", id, "Pending human review, not approved");
    notify(state, app, "Application sent for demo review", `${app.reference} is waiting for an independent human reviewer. No real credit application was sent.`);
    return app;
  });
}
