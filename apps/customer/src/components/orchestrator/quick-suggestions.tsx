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

  // Detect Romanian vs English in the assistant message
  const isRo =
    text.includes("scop") ||
    text.includes("sum") ||
    text.includes("luni") ||
    text.includes("angajar") ||
    text.includes("venit") ||
    text.includes("verific") ||
    text.includes("bună") ||
    text.includes("te rog");

  // 1. Confirmation ("da" / "yes")
  if (text.includes("„da”") || text.includes('"yes"') || text.includes("dacă valorile din documente")) {
    return isRo
      ? [
          { label: "✅ Da, valorile sunt corecte", value: "da" },
          { label: "❌ Nu, vreau să modific", value: "nu" },
        ]
      : [
          { label: "✅ Yes, values are correct", value: "yes" },
          { label: "❌ No, need to adjust", value: "no" },
        ];
  }

  // 2. Preliminary check run ("ok")
  if (text.includes("„ok”") || text.includes('"ok"')) {
    return isRo
      ? [{ label: "🚀 Ok, rulează verificarea", value: "ok" }]
      : [{ label: "🚀 Ok, run preliminary check", value: "ok" }];
  }

  // 3. Employment Type
  if (
    text.includes("employment type") ||
    text.includes("statutul") ||
    text.includes("angajare") ||
    text.includes("options: employed")
  ) {
    return isRo
      ? [
          { label: "💼 Salariat (angajat)", value: "salariat" },
          { label: "🚀 Liber profesionist (PFA)", value: "pfa" },
          { label: "🏖️ Pensionar", value: "pensionar" },
        ]
      : [
          { label: "💼 Employed", value: "employed" },
          { label: "🚀 Self-employed", value: "self_employed" },
          { label: "🏖️ Retired", value: "retired" },
        ];
  }

  // 4. Monthly Obligations
  if (
    text.includes("obligații") ||
    text.includes("obligatii") ||
    text.includes("obligations") ||
    text.includes("rate")
  ) {
    return isRo
      ? [
          { label: "0 RON (fără alte rate)", value: "nu am" },
          { label: "400 RON / lună", value: "400" },
          { label: "800 RON / lună", value: "800" },
        ]
      : [
          { label: "0 RON (no other loans)", value: "none" },
          { label: "400 RON / month", value: "400" },
          { label: "800 RON / month", value: "800" },
        ];
  }

  // 5. Monthly Net Income
  if (text.includes("venit") || text.includes("net income")) {
    return [
      { label: "4.500 RON", value: "4500" },
      { label: "6.000 RON", value: "6000" },
      { label: "7.000 RON", value: "7000" },
      { label: "10.000 RON", value: "10000" },
    ];
  }

  // 6. Employer Name
  if (text.includes("angajator") || text.includes("employer")) {
    return [
      { label: "TechCorp SRL", value: "TechCorp SRL" },
      { label: "Alpha Solutions", value: "Alpha Solutions" },
    ];
  }

  // 7. Tenure / Months with employer
  if (text.includes("vechime") || text.includes("tenure") || text.includes("câte luni lucrezi")) {
    return isRo
      ? [
          { label: "12 luni", value: "12" },
          { label: "24 luni (2 ani)", value: "24" },
          { label: "48 luni (4 ani)", value: "48" },
        ]
      : [
          { label: "12 months", value: "12" },
          { label: "24 months (2 yrs)", value: "24" },
          { label: "48 months (4 yrs)", value: "48" },
        ];
  }

  // 8. Purpose (what is the loan for)
  if (
    text.includes("scopul") ||
    text.includes("scop") ||
    text.includes("pentru ce") ||
    text.includes("purpose") ||
    text.includes("what is the loan for")
  ) {
    return isRo
      ? [
          { label: "🚗 O mașină", value: "pentru o masina" },
          { label: "🏠 Renovare locuință", value: "pentru renovare" },
          { label: "💳 Cheltuieli personale", value: "cheltuieli personale" },
          { label: "🔄 Refinanțare credit", value: "refinantare" },
        ]
      : [
          { label: "🚗 A car", value: "a car" },
          { label: "🏠 Home renovation", value: "home renovation" },
          { label: "💳 Personal expenses", value: "personal expenses" },
          { label: "🔄 Refinancing", value: "refinancing" },
        ];
  }

  // 9. Amount
  if (text.includes("sumă") || text.includes("suma") || text.includes("amount")) {
    return [
      { label: "20.000 RON", value: "20000" },
      { label: "35.000 RON", value: "35000" },
      { label: "50.000 RON", value: "50000" },
      { label: "80.000 RON", value: "80000" },
    ];
  }

  // 10. Term / Period
  if (
    text.includes("perioad") ||
    text.includes("term") ||
    text.includes("luni") ||
    text.includes("months")
  ) {
    return isRo
      ? [
          { label: "24 luni (2 ani)", value: "24" },
          { label: "36 luni (3 ani)", value: "36" },
          { label: "48 luni (4 ani)", value: "48" },
          { label: "60 luni (5 ani)", value: "60" },
        ]
      : [
          { label: "24 months (2 yrs)", value: "24" },
          { label: "36 months (3 yrs)", value: "36" },
          { label: "48 months (4 yrs)", value: "48" },
          { label: "60 months (5 yrs)", value: "60" },
        ];
  }

  // 11. Initial Greeting / General prompt
  if (
    text.includes("bună!") ||
    text.includes("buna!") ||
    text.includes("hi! i'm your credit assistant") ||
    text.includes("could you tell me more") ||
    text.includes("poți să-mi spui mai multe")
  ) {
    return isRo
      ? [
          { label: "💰 Vreau un credit", value: "Vreau un credit" },
          { label: "🚗 Credit auto", value: "Vreau un credit pentru o mașină" },
          { label: "🏠 Credit renovare", value: "Vreau un credit pentru renovare" },
          { label: "ℹ️ Ce produse aveți?", value: "Ce tipuri de credite aveți?" },
        ]
      : [
          { label: "💰 I want a loan", value: "I want a loan" },
          { label: "🚗 Car loan", value: "I want a loan for a car" },
          { label: "🏠 Home renovation", value: "I want a loan for home renovation" },
          { label: "ℹ️ What products do you have?", value: "What loan products do you offer?" },
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
        Sugestii:
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
