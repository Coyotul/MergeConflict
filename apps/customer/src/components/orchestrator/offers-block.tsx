"use client";

import { useState } from "react";
import { Check, ChevronDown, ChevronUp } from "lucide-react";
import type { OffersBlock, Awaiting } from "@banking/demo/orchestrator";
import { formatMoneyString } from "@banking/demo/orchestrator-format";
import { chooseOfferLabel } from "@banking/demo/orchestrator-labels";
import { Button } from "@banking/ui/button";
import { Pill } from "@banking/ui/primitives";

export function OffersBlockComponent({
  block,
  awaiting,
  onChooseOffer,
  disabled,
}: {
  block: OffersBlock;
  awaiting: Awaiting;
  onChooseOffer: (offerId: string) => void;
  disabled: boolean;
}) {
  const [expandedOffer, setExpandedOffer] = useState<string | null>(null);
  const canChoose = awaiting.kind === "offer_choice";

  return (
    <div className="mt-4 space-y-3">
      {block.offers.map((offer) => {
        const isSelected = offer.offer_id === block.selected_offer_id;
        const isExpanded = expandedOffer === offer.offer_id;

        return (
          <div
            key={offer.offer_id}
            className={`rounded-2xl border p-5 ${
              isSelected
                ? "border-ink bg-ink/5 ring-2 ring-ink"
                : "border-slate-200 bg-white"
            }`}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex-1">
                <div className="mb-3 flex items-center gap-2">
                  <p className="text-xl font-semibold text-ink">
                    {offer.term_months} months
                  </p>
                  {isSelected && (
                    <Pill tone="brand">
                      <Check className="size-3" />
                      Selected
                    </Pill>
                  )}
                  {offer.simulated && (
                    <span className="text-[10px] text-slate-400">
                      · Simulated
                    </span>
                  )}
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <p className="text-xs text-slate-500">Monthly installment</p>
                    <p className="mt-1 text-lg font-semibold text-ink">
                      {formatMoneyString(
                        offer.monthly_installment.amount,
                        offer.monthly_installment.currency
                      )}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-slate-500">Total cost</p>
                    <p className="mt-1 text-lg font-semibold text-ink">
                      {formatMoneyString(offer.total_cost.amount, offer.total_cost.currency)}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-slate-500">Annual interest</p>
                    <p className="mt-1 text-sm font-semibold text-slate-700">
                      {offer.annual_interest_rate_percent}%
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-slate-500">Total repayment</p>
                    <p className="mt-1 text-sm font-semibold text-slate-700">
                      {formatMoneyString(
                        offer.total_repayment.amount,
                        offer.total_repayment.currency
                      )}
                    </p>
                  </div>
                </div>
                {offer.assumptions.length > 0 && (
                  <div className="mt-3">
                    <button
                      type="button"
                      aria-expanded={isExpanded}
                      aria-controls={`assumptions-${offer.offer_id}`}
                      onClick={() =>
                        setExpandedOffer(isExpanded ? null : offer.offer_id)
                      }
                      className="flex items-center gap-1 text-xs font-medium text-brand-ink hover:underline"
                    >
                      {isExpanded ? (
                        <>
                          <ChevronUp className="size-3" />
                          Hide assumptions
                        </>
                      ) : (
                        <>
                          <ChevronDown className="size-3" />
                          Show assumptions
                        </>
                      )}
                    </button>
                    {isExpanded && (
                      <ul
                        id={`assumptions-${offer.offer_id}`}
                        className="mt-2 space-y-1 rounded-lg bg-slate-50 p-3"
                      >
                        {offer.assumptions.map((assumption, index) => (
                          <li
                            key={index}
                            className="text-xs leading-relaxed text-slate-600"
                          >
                            • {assumption}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
              </div>
            </div>
            {!isSelected && canChoose && (
              <Button
                className="mt-4 w-full"
                disabled={disabled}
                onClick={() => onChooseOffer(offer.offer_id)}
              >
                {chooseOfferLabel(
                  offer.term_months,
                  formatMoneyString(
                    offer.monthly_installment.amount,
                    offer.monthly_installment.currency
                  )
                )}
              </Button>
            )}
          </div>
        );
      })}
    </div>
  );
}
