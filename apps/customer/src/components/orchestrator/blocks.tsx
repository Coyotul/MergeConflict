"use client";

import type { TurnResponse } from "@banking/demo/orchestrator";
import { canConfirm } from "@banking/demo/orchestrator-state";
import { isKnownBlock } from "@banking/demo/orchestrator";
import type { ChatState } from "@banking/demo/orchestrator-state";
import { DocumentChecklistBlockComponent } from "./document-checklist-block";
import { ExtractedFieldsBlockComponent } from "./extracted-fields-block";
import { OffersBlockComponent } from "./offers-block";
import { SummaryBlockComponent } from "./summary-block";
import {
  EligibilityResultBlock,
  ApplicationSubmittedBlock,
  EscalationBlock,
} from "./status-blocks";

export function Blocks({
  latest,
  state,
  onSend,
  onUpload,
  onChooseOffer,
  onConfirm,
  disabled,
}: {
  latest: TurnResponse;
  state: ChatState;
  onSend: (text: string) => void;
  onUpload: (docType: string, file: File) => void;
  onChooseOffer: (offerId: string) => void;
  onConfirm: (summaryVersion: string, decision: "confirm" | "decline") => void;
  disabled: boolean;
}) {
  if (!latest.blocks.length) {
    return null;
  }

  return (
    <div>
      {latest.blocks.map((block, index) => {
        if (!isKnownBlock(block)) {
          return null;
        }

        switch (block.type) {
          case "document_checklist":
            return (
              <DocumentChecklistBlockComponent
                key={index}
                block={block}
                awaiting={latest.awaiting}
                onUpload={onUpload}
                disabled={disabled}
              />
            );

          case "extracted_fields":
            return (
              <ExtractedFieldsBlockComponent
                key={index}
                block={block}
                onSend={onSend}
                disabled={disabled}
              />
            );

          case "eligibility_result":
            return <EligibilityResultBlock key={index} block={block} />;

          case "offers":
            return (
              <OffersBlockComponent
                key={index}
                block={block}
                awaiting={latest.awaiting}
                onChooseOffer={onChooseOffer}
                disabled={disabled}
              />
            );

          case "application_summary":
            return (
              <SummaryBlockComponent
                key={index}
                block={block}
                canConfirm={canConfirm(state, block.summary)}
                onConfirm={onConfirm}
                disabled={disabled}
              />
            );

          case "application_submitted":
            return <ApplicationSubmittedBlock key={index} block={block} />;

          case "escalation":
            return <EscalationBlock key={index} block={block} />;

          default:
            return null;
        }
      })}
    </div>
  );
}
