"use client";

import { Sparkles } from "lucide-react";
import type { ChatState } from "@banking/demo/orchestrator-state";

export interface SuggestionItem {
  label: string;
  value: string;
}

export function getQuickSuggestions(state: ChatState): SuggestionItem[] {
  if (state.pending || !state.entries.length) {
    return [];
  }

  // Find the last assistant message
  const assistantEntries = state.entries.filter((e) => e.role === "assistant");
  if (!assistantEntries.length) {
    return [];
  }

  const lastAssistant = assistantEntries[assistantEntries.length - 1];
  const text = lastAssistant.text.toLowerCase();

  // Check blocks from latest turn
  const blocks = state.latest?.blocks ?? [];
  const eligibilityBlock = blocks.find((b) => b.type === "eligibility_result") as
    | { type: "eligibility_result"; result: { status: string; reasons?: Array<{ message: string }> } }
    | undefined;

  const currentStage = state.latest?.progress?.stage;

  // 1. Eligibility REJECTED / Not satisfied (e.g. Photo 3)
  if (
    currentStage === "not_eligible" ||
    eligibilityBlock?.result?.status === "not_satisfied" ||
    text.includes("preliminary conditions are not met") ||
    text.includes("not satisfied") ||
    text.includes("condițiile preliminare nu sunt îndeplinite") ||
    text.includes("below minimum") ||
    text.includes("exceeds maximum")
  ) {
    return [
      { label: "💬 Speak with a loan advisor", value: "I want to speak with a loan advisor" },
      { label: "📉 Lower loan amount", value: "Can I simulate a lower loan amount?" },
      { label: "👥 Add a co-borrower", value: "Can I add a co-borrower to qualify?" },
      { label: "📋 Explore other loan products", value: "What other credit products do you offer?" },
      { label: "🔄 Start fresh", value: "I want to start a new application" },
    ];
  }

  // 2. Manual Review Required
  if (
    eligibilityBlock?.result?.status === "manual_review" ||
    text.includes("manual review") ||
    text.includes("review by a human advisor") ||
    text.includes("analiza unui consultant")
  ) {
    return [
      { label: "👤 Connect with advisor", value: "Please connect me with a loan advisor" },
      { label: "📄 What extra documents are needed?", value: "What extra documents are needed for manual review?" },
      { label: "⏱️ How long does review take?", value: "How long does manual review take?" },
    ];
  }

  // 3. Document Rejected / Could not be used
  if (
    text.includes("could not be used") ||
    text.includes("nu a putut fi folosit") ||
    text.includes("couldn't use your document")
  ) {
    return [
      { label: "📤 Upload replacement file", value: "I will upload a clearer document" },
      { label: "❓ Why was it rejected?", value: "Why could my document not be used?" },
      { label: "💬 Talk to support", value: "I need human support" },
    ];
  }

  // 4. Confirmation of document values (e.g. Photo 2)
  if (
    text.includes("check the values from your documents") ||
    text.includes("reply \"yes\" if") ||
    text.includes("răspunde „da”") ||
    text.includes("verifică valorile din documente")
  ) {
    return [
      { label: "✅ Yes, document values are correct", value: "yes" },
      { label: "✏️ No, I need to adjust values", value: "no" },
    ];
  }

  // 5. Preliminary check run ("ok")
  if (
    text.includes("reply \"ok\" to run it") ||
    text.includes("scrie „ok” ca s-o rulez") ||
    text.includes("ready for a preliminary check")
  ) {
    return [
      { label: "🚀 Ok, run preliminary check", value: "ok" },
      { label: "📄 What are the check criteria?", value: "What are the preliminary eligibility criteria?" },
    ];
  }

  // 6. Employment Duration / Tenure
  if (
    text.includes("employment duration") ||
    text.includes("vechime") ||
    text.includes("tenure") ||
    text.includes("how many months have you been with") ||
    text.includes("luni lucrezi")
  ) {
    return [
      { label: "12 months (1 yr)", value: "12" },
      { label: "24 months (2 yrs)", value: "24" },
      { label: "36 months (3 yrs)", value: "36" },
      { label: "48 months (4 yrs)", value: "48" },
    ];
  }

  // 7. Employment Type
  if (
    text.includes("employment type") ||
    text.includes("employment status") ||
    text.includes("statutul") ||
    text.includes("options: employed")
  ) {
    return [
      { label: "💼 Employed (salariat)", value: "employed" },
      { label: "🚀 Self-employed (PFA)", value: "self_employed" },
      { label: "🏖️ Retired (pensionar)", value: "retired" },
    ];
  }

  // 8. Monthly Obligations
  if (
    text.includes("obligations") ||
    text.includes("obligații") ||
    text.includes("existing monthly obligations") ||
    text.includes("installments") ||
    text.includes("alte rate")
  ) {
    return [
      { label: "0 RON (no other loans)", value: "0" },
      { label: "400 RON / month", value: "400" },
      { label: "800 RON / month", value: "800" },
    ];
  }

  // 9. Monthly Net Income
  if (text.includes("net income") || text.includes("venit")) {
    return [
      { label: "4,500 RON", value: "4500" },
      { label: "6,000 RON", value: "6000" },
      { label: "7,500 RON", value: "7500" },
      { label: "10,000 RON", value: "10000" },
    ];
  }

  // 10. Employer Name
  if (text.includes("employer") || text.includes("angajator")) {
    return [
      { label: "TechCorp SRL", value: "TechCorp SRL" },
      { label: "Alpha Solutions", value: "Alpha Solutions" },
      { label: "Enterprise Solutions", value: "Enterprise Solutions" },
    ];
  }

  // 11. Purpose (what is the loan for)
  if (
    text.includes("purpose") ||
    text.includes("what is the loan for") ||
    text.includes("scop") ||
    text.includes("pentru ce")
  ) {
    return [
      { label: "🚗 A car", value: "a car" },
      { label: "🏠 Home renovation", value: "home renovation" },
      { label: "💳 Personal expenses", value: "personal expenses" },
      { label: "🔄 Loan refinancing", value: "refinancing" },
    ];
  }

  // 12. Amount
  if (text.includes("amount") || text.includes("sumă") || text.includes("suma")) {
    return [
      { label: "20,000 RON", value: "20000" },
      { label: "35,000 RON", value: "35000" },
      { label: "50,000 RON", value: "50000" },
      { label: "80,000 RON", value: "80000" },
    ];
  }

  // 13. Term / Period
  if (
    text.includes("term") ||
    text.includes("months") ||
    text.includes("perioad") ||
    text.includes("luni")
  ) {
    return [
      { label: "24 months (2 yrs)", value: "24" },
      { label: "36 months (3 yrs)", value: "36" },
      { label: "48 months (4 yrs)", value: "48" },
      { label: "60 months (5 yrs)", value: "60" },
    ];
  }

  // 14. Initial Greeting / General prompt
  if (
    text.includes("i'm your credit assistant") ||
    text.includes("help you apply") ||
    text.includes("could you tell me more") ||
    text.includes("bună!")
  ) {
    return [
      { label: "💰 I want a loan", value: "I want a loan" },
      { label: "🚗 Car loan", value: "I want a loan for a car" },
      { label: "🏠 Home renovation", value: "I want a loan for home renovation" },
      { label: "ℹ️ What products do you offer?", value: "What loan products do you offer?" },
    ];
  }

  return [];
}

export function QuickSuggestions({
  state,
  onSelect,
  disabled,
}: {
  state: ChatState;
  onSelect: (text: string) => void;
  disabled: boolean;
}) {
  const suggestions = getQuickSuggestions(state);

  if (!suggestions.length) {
    return null;
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5 pt-1 pb-2">
      <span className="flex items-center gap-1 text-[11px] font-medium text-slate-500 mr-1">
        <Sparkles className="size-3 text-amber-500" />
        Suggestions:
      </span>
      {suggestions.map((item) => (
        <button
          key={item.label}
          type="button"
          disabled={disabled}
          onClick={() => onSelect(item.value)}
          className="inline-flex items-center rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-700 shadow-sm transition-all hover:border-primary hover:bg-brand-soft/60 hover:text-ink active:scale-95 disabled:opacity-50"
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
