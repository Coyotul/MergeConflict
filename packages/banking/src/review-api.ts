// Client for the Python review API (contracts/http/reviews.md), same host as the chat orchestrator.
const BASE = process.env.NEXT_PUBLIC_ORCHESTRATOR_URL ?? "http://127.0.0.1:8000";
export const DEMO_REVIEWER_ID = "reviewer-demo";

export type ReviewStatus = "PENDING_HUMAN_REVIEW" | "MORE_INFORMATION_REQUIRED" | "APPROVED" | "REJECTED";
export type RequestableDocument = "id_card" | "payslip" | "bank_statement";

export const documentLabels: Record<string, string> = {
  id_card: "ID card", payslip: "Payslip", bank_statement: "Bank statement",
};

export interface HistoryView { to_status: ReviewStatus; status_label: string; reason: string; at: string }
export interface CustomerApplication {
  id: string; reference: string; product_code: string; status: ReviewStatus; status_label: string;
  amount: string | number | null; term_months: number | null; monthly_installment: string | null;
  total_cost: string | null; offer_updated: boolean; history: HistoryView[];
  open_request: { id: string; doc_type: RequestableDocument; reason: string } | null;
  created_at: string; updated_at: string;
}
export interface UploadResult { application: CustomerApplication; accepted: boolean; reasons: string[] }

export interface QueueItem {
  id: string; reference: string; customer_name: string | null; product_code: string;
  amount: string | number | null; status: ReviewStatus; status_label: string; updated_at: string;
}
export interface ReviewDocument {
  document_id: string; doc_type: string; origin: "chat" | "information_request"; status: string;
  filename: string | null; extracted_fields: Record<string, unknown>; validation: { valid?: boolean; reasons?: string[] } | null;
  uploaded_at: string; superseded_by: string | null;
}
export interface ReviewDetail {
  id: string; reference: string; customer_id: string; product_code: string; status: ReviewStatus; status_label: string;
  version: number; snapshot: Record<string, any>; current: Record<string, any>; documents: ReviewDocument[];
  history: { from_status: ReviewStatus | null; to_status: ReviewStatus; actor: string; reason: string; at: string }[];
  requests: { id: string; doc_type: string; reason: string; status: "open" | "fulfilled"; created_at: string }[];
  changed_fields: { field: string; before: unknown; after: unknown }[];
  customer: CustomerApplication;
}
export type Decision =
  | { action: "approve" | "reject"; reason: string; version: number }
  | { action: "request_document"; reason: string; version: number; doc_type: RequestableDocument };

export class ReviewApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function call<T>(path: string, init: RequestInit & { headers: Record<string, string> }): Promise<T> {
  const response = await fetch(`${BASE}${path}`, { cache: "no-store", ...init });
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new ReviewApiError(response.status, body?.detail?.message ?? `Request failed (${response.status})`);
  return body as T;
}

const customer = (id: string) => ({ "X-Customer-Id": id });
const reviewer = { "X-Reviewer-Id": DEMO_REVIEWER_ID };

export const listMyApplications = (customerId: string) =>
  call<{ applications: CustomerApplication[] }>("/applications", { headers: customer(customerId) }).then((r) => r.applications);

export function uploadRequested(customerId: string, appId: string, requestId: string, file: File) {
  const form = new FormData();
  form.append("file", file, file.name);
  return call<UploadResult>(`/applications/${appId}/requests/${requestId}/document`, {
    method: "POST", body: form, headers: customer(customerId),
  });
}

export const listQueue = (status?: ReviewStatus) =>
  call<{ applications: QueueItem[] }>(`/review/applications${status ? `?status=${status}` : ""}`, { headers: reviewer })
    .then((r) => r.applications);
export const getReview = (id: string) => call<ReviewDetail>(`/review/applications/${id}`, { headers: reviewer });
export const decide = (id: string, decision: Decision) =>
  call<ReviewDetail>(`/review/applications/${id}/decision`, {
    method: "POST", body: JSON.stringify(decision), headers: { ...reviewer, "Content-Type": "application/json" },
  });

// The browser cannot attach the reviewer header to a plain link, so documents are fetched and opened as blobs.
export async function openDocument(id: string, documentId: string) {
  const response = await fetch(`${BASE}/review/applications/${id}/documents/${documentId}`, { headers: reviewer });
  if (!response.ok) throw new ReviewApiError(response.status, "Document file is unavailable.");
  window.open(URL.createObjectURL(await response.blob()), "_blank", "noopener");
}
