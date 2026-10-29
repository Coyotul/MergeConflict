// Customer-facing labels for orchestrator wire values (pure; no React).

/** Labels keyed by the contract progress stage names (contracts/http/README.md). */
export const STEP_LABELS: Record<string, string> = {
  discovery: "Discovery",
  collecting_information: "Your details",
  eligibility: "Eligibility",
  documents: "Documents",
  offer_selection: "Offers",
  awaiting_confirmation: "Confirm",
  submitted: "Submitted",
};

/** Turn a snake_case or UPPER_SNAKE value into a neutral sentence-case label. */
export function humaniseStatus(value: string): string {
  const words = value.replace(/[_-]+/g, " ").trim().toLowerCase();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : value;
}

export function stepLabel(stage: string): string {
  return STEP_LABELS[stage] ?? humaniseStatus(stage);
}

const STEP_STATUS_TEXT: Record<string, string> = {
  done: "completed",
  current: "current step",
  todo: "not started",
};

/** Screen-reader text for a progress step status. */
export function stepStatusText(status: string): string {
  return STEP_STATUS_TEXT[status] ?? humaniseStatus(status);
}

const DOCUMENT_STATUS_LABELS: Record<string, string> = {
  accepted: "Accepted",
  rejected: "Rejected",
  requested: "Requested",
  processing: "Processing",
  uploaded: "Uploaded",
};

export function documentStatusLabel(status: string): string {
  return DOCUMENT_STATUS_LABELS[status] ?? humaniseStatus(status);
}

export function chooseOfferLabel(termMonths: number, monthlyInstallment: string): string {
  return `Choose ${termMonths}-month offer (${monthlyInstallment}/month)`;
}

export function confirmFieldLabel(fieldLabel: string): string {
  return `Confirm ${fieldLabel}`;
}

export function confirmFieldMessage(fieldLabel: string): string {
  return `Yes, ${fieldLabel} is correct`;
}

export function documentValueLabel(fieldLabel: string): string {
  return `Use document value for ${fieldLabel}`;
}

export function documentValueMessage(fieldLabel: string): string {
  return `Yes, use the document value for ${fieldLabel}`;
}
