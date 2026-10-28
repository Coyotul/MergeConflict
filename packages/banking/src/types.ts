export type Money = string;
export type Role = "customer" | "reviewer";
export interface Actor { id: string; name: string; role: Role }
export type ApplicationStatus = "DRAFT" | "AWAITING_DOCUMENTS" | "READY_FOR_SUBMISSION" | "PENDING_HUMAN_REVIEW" | "MORE_INFORMATION_REQUIRED" | "APPROVED" | "REJECTED" | "CANCELLED";
export type DocumentKind = "identity" | "income" | "statement";
export type DocumentStatus = "MISSING" | "FORMAT_ACCEPTED";
export interface Customer {
  id: string; name: string; email: string; initials: string;
  monthlyIncome: Money; monthlyExpenses: Money; balance: Money; employer: string;
}
export interface PolicySource { id: string; title: string; version: string; effectiveDate: string; section: string; content: string }
export interface Product {
  id: string; name: string; description: string; annualRate: Money; fee: Money; monthlyInsurance: Money;
  minAmount: Money; maxAmount: Money; minMonths: number; maxMonths: number; policyId: string;
}
export interface Loan {
  id: string; customerId: string; name: string; principal: Money; annualRate: Money;
  remainingMonths: number; originalAmount: Money; nextPaymentDate: string;
}
export interface PaymentRow { month: number; payment: Money; principal: Money; interest: Money; balance: Money }
export interface LoanQuote {
  amount: Money; months: number; annualRate: Money; installment: Money; monthlyPayment: Money;
  fee: Money; monthlyInsurance: Money; interestCost: Money; totalCost: Money; schedule: PaymentRow[];
}
export interface Assessment {
  status: "PRELIMINARY_REQUIREMENTS_SATISFIED" | "MANUAL_REVIEW_REQUIRED";
  debtRatio: Money; threshold: Money; reasons: string[]; policyVersion: string;
}
export interface ApplicationDocument { kind: DocumentKind; status: DocumentStatus; name?: string; mimeType?: string; size?: number; uploadedAt?: string }
export interface HistoryEntry { id: string; status: ApplicationStatus; at: string; actor: string; description: string }
export interface ReviewNote { id: string; author: string; at: string; text: string; internal: boolean }
export interface LoanApplication {
  id: string; reference: string; customerId: string; customer: Customer; reviewerId: string;
  productId: string; policyVersion: string; amount: Money; months: number; quote: LoanQuote; assessment: Assessment;
  status: ApplicationStatus; createdAt: string; updatedAt: string; documents: ApplicationDocument[];
  requestedDocument?: DocumentKind; requestReason?: string; decisionReason?: string;
  history: HistoryEntry[]; notes: ReviewNote[];
}
export type MessageKind = "text" | "options" | "products" | "modify" | "loan-details" | "loan" | "repayment" | "refinance" | "documents" | "applications" | "support" | "contract";
export interface ChatMessage {
  id: string; role: "user" | "assistant"; text: string; at: string; kind: MessageKind;
  sources?: string[]; params?: { amount?: Money; months?: number; productId?: string };
}
export interface Notification { id: string; customerId: string; title: string; text: string; at: string; read: boolean; applicationId?: string }
export interface AuditEvent { id: string; actorId: string; actor: string; action: string; objectId: string; at: string; result: string }
export interface Consent { financialInsights: boolean; notifications: boolean }
export interface Snapshot {
  actor: Actor; customer: Customer; products: Product[]; policies: PolicySource[]; loans: Loan[];
  applications: LoanApplication[]; messages: ChatMessage[]; notifications: Notification[]; audit: AuditEvent[]; consent: Consent;
}
export interface LoginCredentials { email: string; password: string }
export interface Session { token: string; actor: Actor; expiresAt: string }
export interface IdempotencyRecord { actorId: string; key: string; fingerprint: string; applicationId: string }
export interface DemoStore {
  version: 1; customers: Customer[]; products: Product[]; policies: PolicySource[]; loans: Loan[];
  applications: LoanApplication[]; messages: Record<string, ChatMessage[]>; notifications: Notification[];
  audit: AuditEvent[]; consents: Record<string, Consent>; idempotency: IdempotencyRecord[];
}
export interface RepaymentQuote {
  current: LoanQuote; reducedPayment: LoanQuote; reducedTerm: LoanQuote; repayment: Money;
  newPrincipal: Money; earlyFee: Money; paymentSavings: Money; interestSavings: Money; monthsSaved: number;
}
export interface RefinanceQuote { currentMonthly: Money; currentTotal: Money; newQuote: LoanQuote; monthlySavings: Money; totalSavings: Money; principal: Money }
