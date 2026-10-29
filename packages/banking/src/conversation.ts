import type { ChatMessage, DemoStore } from "./types";

export function interpretMessage(text: string, store: DemoStore, customerId: string): Omit<ChatMessage, "id" | "at" | "role"> {
  const normalized = text.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  const matches = (pattern: RegExp) => pattern.test(normalized);
  const result = (kind: ChatMessage["kind"], reply: string, sources?: string[], params?: ChatMessage["params"]) => ({ kind, text: reply, sources, params });
  if (matches(/(back to options|main menu|start over|optiuni|options|hello|^hi$|salut)/)) return result("options", "What would you like to do? Choose a starting point below, or tell me in your own words.");
  if (matches(/(human|consultant|representative|support|difficulty|cannot pay|can't pay|nu pot plati|ajutor)/)) return result("support", "You do not have to work through this alone. I can record a demo support request with your conversation context. No real bank representative is contacted in this prototype.");
  if (matches(/(status|application|cerer|submitted)/) && !matches(/(apply|want|doresc|vreau)/)) return result("applications", "Here are the recorded statuses of your synthetic applications. Only a human reviewer can record the final demo credit decision.");
  if (matches(/(document|upload|acte|incarc)/)) return result("documents", "The demo checklist asks for an identity document and proof of income. A reviewer can request an account statement. Only filename, type and size are saved — no file bytes or OCR results.", ["personal-policy"]);
  if (matches(/(contract|clause|clauz|agreement)/)) return result("contract", "I can explain the synthetic policy assumptions below. Contract extraction is not connected, so I cannot claim to have read your real agreement. This explanation is not legal advice.", ["repayment-policy"]);
  if (matches(/(current loan details|existing loan|my loans|balance|next payment|informatii|sold|scadent|schedule)/)) return result("loan-details", "Here is your current loan information from the synthetic profile. Balances are principal only, not authoritative full-settlement amounts.");
  if (matches(/(refinanc|consolidat|lower my|reduce my|monthly payment|rata mai mica)/)) return result("refinance", "Let's compare your current obligations with an indicative refinancing scenario. A lower monthly payment can still mean a higher total cost.", ["repayment-policy"]);
  if (matches(/(early repay|repay|ramburs|pay off|anticipat)/)) return result("repayment", "Choose a partial repayment amount to compare a lower installment with a shorter term. Full repayment needs an authoritative settlement quote; no payment will be executed here.", ["repayment-policy"]);
  if (matches(/(change my|modify|modific|schimb|restructur)/)) return result("modify", "What would you like to change about your current loan? We can compare the options before you make any decision.");
  const productId = matches(/(mortgage|ipotec|home loan)/) ? "mortgage" : matches(/(car loan|auto|masina)/) ? "car" : matches(/(personal|nevoi personale)/) ? "personal" : undefined;
  const amountMatch = normalized.match(/(\d[\d ,.]*)\s*(?:ron|lei)/);
  const monthsMatch = normalized.match(/(\d+)\s*(month|months|luni|year|years|ani)/);
  const previous = [...(store.messages[customerId] ?? [])].reverse().find((m) => m.role === "assistant");
  const isFollowUp = previous?.kind === "loan" && (Boolean(amountMatch) || Boolean(monthsMatch));
  if (productId || isFollowUp || matches(/(loan|credit|borrow|imprumut)/)) {
    const selected = productId ?? (isFollowUp ? previous?.params?.productId : undefined);
    if (!selected) return result("products", "Of course. First, what kind of loan do you have in mind? All product terms here are fictional demo configurations.");
    const numeric = amountMatch?.[1].replace(/[ ,]/g, "");
    const amount = numeric && /^\d+(\.\d{1,2})?$/.test(numeric) ? numeric : undefined;
    const months = monthsMatch ? Number(monthsMatch[1]) * (/year|ani/.test(monthsMatch[2]) ? 12 : 1) : undefined;
    const product = store.products.find((p) => p.id === selected)!;
    return result("loan", `Let's explore a ${product.name.toLowerCase()}. Set the amount and duration below. The deterministic calculator includes the configured interest, fee and insurance. Nothing is submitted without your confirmation.`, [product.policyId], { productId: selected, amount: amount ?? (isFollowUp ? previous?.params?.amount : undefined), months: months ?? (isFollowUp ? previous?.params?.months : undefined) });
  }
  return result("options", "I haven't identified a supported banking request yet. Are you looking for a new loan, a change to your existing loan, or information about it? You can also ask for human support. This is a guided demo, not a live AI model.");
}
