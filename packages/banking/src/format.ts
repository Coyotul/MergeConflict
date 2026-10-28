import type { ApplicationStatus, DocumentKind, Money } from "./types";

export const statusLabels: Record<ApplicationStatus, string> = {
  DRAFT: "Draft", AWAITING_DOCUMENTS: "Documents needed", READY_FOR_SUBMISSION: "Ready to submit",
  PENDING_HUMAN_REVIEW: "In human review", MORE_INFORMATION_REQUIRED: "Information requested",
  APPROVED: "Approved · demo", REJECTED: "Rejected · demo", CANCELLED: "Cancelled",
};
export const documentLabels: Record<DocumentKind, string> = { identity: "Identity document", income: "Proof of income", statement: "Account statement" };
export function formatMoney(value: Money | number, digits = 2) {
  return new Intl.NumberFormat("en-GB", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(Number(value)) + " RON";
}
export function formatDate(date: string, includeTime = false) {
  return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", ...(includeTime ? { hour: "2-digit", minute: "2-digit" } : {}) }).format(new Date(date));
}
export function initials(name: string) { return name.split(" ").map((part) => part[0]).slice(0, 2).join(""); }
