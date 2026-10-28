// Types mirroring contracts/http/chat.openapi.yaml (snake_case wire format)

export interface CitationRef {
  id: string;
  publisher: string;
  title: string;
  url: string;
  section?: string | null;
  effective_date?: string | null;
}

export interface ChatMessageView {
  role: "customer" | "assistant";
  text: string;
  citations: CitationRef[];
  created_at: string;
}

export type AwaitingKind = "text" | "document" | "offer_choice" | "confirmation" | "none";

export interface Awaiting {
  kind: AwaitingKind;
  document_types?: string[];
  summary_version?: string | null;
}

export interface ProgressStep {
  stage: string;
  status: "done" | "current" | "todo";
}

export interface Progress {
  flow: "none" | "product_info" | "credit_application";
  stage: string | null;
  steps: ProgressStep[];
}

export interface Money {
  amount: string;
  currency: string;
}

export type Product =
  | "personal_loan"
  | "refinancing_unsecured"
  | "refinancing_mortgage"
  | "mortgage_casa_ta"
  | "mortgage_casa_ta_verde"
  | "mortgage_noua_casa"
  | "mortgage_residential_projects"
  | "overdraft"
  | "credit_card"
  | "general";

export interface LoanOffer {
  offer_id: string;
  product_code: Product;
  amount: Money;
  term_months: number;
  annual_interest_rate_percent: string;
  monthly_installment: Money;
  total_repayment: Money;
  total_cost: Money;
  fees: Money;
  assumptions: string[];
  indicative?: boolean;
  simulated?: boolean;
}

export interface EligibilityResult {
  status: "satisfied" | "not_satisfied" | "more_information_required" | "manual_review";
  reasons: { code: string; message: string }[];
  rule_version: string;
  missing_fields?: string[];
  simulated?: boolean;
}

export interface DocumentChecklistItem {
  doc_type: string;
  label: string;
  status: string;
  rejection_reason?: string | null;
}

export interface ExtractedFieldView {
  field: string;
  label: string;
  value: string;
  source: string;
  confidence?: number | null;
  needs_confirmation: boolean;
  conflict_with?: string | null;
}

export interface SummaryField {
  label: string;
  value: string;
  source: string;
}

export interface ApplicationSummary {
  summary_version: string;
  application_id: string;
  product_code: Product;
  product_name: string;
  amount: Money;
  term_months: number;
  offer: LoanOffer;
  fields: SummaryField[];
  documents: DocumentChecklistItem[];
}

export interface DocumentChecklistBlock {
  type: "document_checklist";
  items: DocumentChecklistItem[];
}

export interface ExtractedFieldsBlock {
  type: "extracted_fields";
  fields: ExtractedFieldView[];
}

export interface EligibilityResultBlock {
  type: "eligibility_result";
  result: EligibilityResult;
}

export interface OffersBlock {
  type: "offers";
  offers: LoanOffer[];
  selected_offer_id?: string | null;
}

export interface ApplicationSummaryBlock {
  type: "application_summary";
  summary: ApplicationSummary;
}

export interface ApplicationSubmittedBlock {
  type: "application_submitted";
  application_id: string;
  status: string;
}

export interface EscalationBlock {
  type: "escalation";
  ticket_id: string;
  message: string;
}

export type KnownBlock =
  | DocumentChecklistBlock
  | ExtractedFieldsBlock
  | EligibilityResultBlock
  | OffersBlock
  | ApplicationSummaryBlock
  | ApplicationSubmittedBlock
  | EscalationBlock;

export interface UnknownBlock {
  type: string;
  [key: string]: unknown;
}

export type Block = KnownBlock | UnknownBlock;

export interface TurnResponse {
  session_id: string;
  turn_id: string;
  session_version: number;
  messages: ChatMessageView[];
  awaiting: Awaiting;
  progress: Progress;
  blocks: Block[];
  simulated: boolean;
}

export interface SessionView {
  session_id: string;
  created_at: string;
  messages: ChatMessageView[];
  latest: TurnResponse;
}

export interface ErrorBody {
  code: string;
  message: string;
  retryable?: boolean;
}

export class OrchestratorError extends Error {
  constructor(
    public status: number,
    public code: string,
    public retryable: boolean,
    message: string
  ) {
    super(message);
  }
}

const ORCHESTRATOR_URL = process.env.NEXT_PUBLIC_ORCHESTRATOR_URL ?? "http://127.0.0.1:8000";

export function isKnownBlock(block: Block): block is KnownBlock {
  return [
    "document_checklist",
    "extracted_fields",
    "eligibility_result",
    "offers",
    "application_summary",
    "application_submitted",
    "escalation",
  ].includes(block.type);
}

export function createOrchestratorClient(
  customerId: string,
  baseUrl: string = ORCHESTRATOR_URL,
  fetchImpl: typeof fetch = fetch
) {
  async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const url = `${baseUrl}${path}`;
    const headers = new Headers(options.headers);
    headers.set("X-Customer-Id", customerId);

    let response: Response;
    try {
      response = await fetchImpl(url, {
        ...options,
        headers,
        signal: AbortSignal.timeout(60000),
      });
    } catch {
      // Network failure or timeout
      throw new OrchestratorError(
        0,
        "unavailable",
        true,
        "The AI assistant service is not reachable. Start it with: uvicorn src.api.app:create_app --factory"
      );
    }

    if (!response.ok) {
      let errorBody: ErrorBody | null = null;
      try {
        errorBody = await response.json();
      } catch {
        // Non-JSON error response
      }

      if (errorBody?.code) {
        throw new OrchestratorError(
          response.status,
          errorBody.code,
          errorBody.retryable ?? response.status >= 500,
          errorBody.message
        );
      } else {
        throw new OrchestratorError(
          response.status,
          "request_failed",
          response.status >= 500,
          "The request failed."
        );
      }
    }

    try {
      return await response.json();
    } catch {
      // JSON parse failure on successful response
      const retryable = response.status >= 500 || (response.status >= 200 && response.status < 300);
      throw new OrchestratorError(
        response.status,
        "invalid_response",
        retryable,
        "The AI assistant returned an unreadable response."
      );
    }
  }

  return {
    async createSession(): Promise<TurnResponse> {
      return request<TurnResponse>("/chat/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
    },

    async sendMessage(sessionId: string, text: string): Promise<TurnResponse> {
      return request<TurnResponse>(`/chat/sessions/${sessionId}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
    },

    async uploadDocument(
      sessionId: string,
      docType: string,
      file: Blob,
      filename: string
    ): Promise<TurnResponse> {
      const formData = new FormData();
      formData.append("doc_type", docType);
      formData.append("file", file, filename);

      return request<TurnResponse>(`/chat/sessions/${sessionId}/documents`, {
        method: "POST",
        body: formData,
      });
    },

    async selectOffer(sessionId: string, offerId: string): Promise<TurnResponse> {
      return request<TurnResponse>(`/chat/sessions/${sessionId}/offer-selection`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ offer_id: offerId }),
      });
    },

    async confirm(
      sessionId: string,
      summaryVersion: string,
      decision: "confirm" | "decline"
    ): Promise<TurnResponse> {
      return request<TurnResponse>(`/chat/sessions/${sessionId}/confirmation`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ summary_version: summaryVersion, decision }),
      });
    },

    async getSession(sessionId: string): Promise<SessionView> {
      return request<SessionView>(`/chat/sessions/${sessionId}`, {
        method: "GET",
      });
    },
  };
}
