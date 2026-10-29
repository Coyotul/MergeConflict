"use client";

import { BookOpen } from "lucide-react";
import { lastAssistantEntryIndex, type ChatState } from "@banking/demo/orchestrator-state";
import { AssistantAvatar } from "@banking/ui/primitives";
import { ProgressSteps } from "./progress-steps";
import { Blocks } from "./blocks";

function Citations({ citations }: { citations: Array<{ id: string; publisher: string; title: string; url: string }> }) {
  if (!citations.length) return null;

  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-2">
      <span className="text-[10px] text-slate-400">Sources</span>
      {citations.map((citation) => {
        const isLink = /^https?:\/\//i.test(citation.url);
        const content = (
          <>
            <BookOpen className="size-3" />
            {citation.title} · {citation.publisher}
          </>
        );

        return isLink ? (
          <a
            key={citation.id}
            href={citation.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded-md bg-white px-2 py-1 text-[10px] font-medium text-brand-ink ring-1 ring-slate-200 hover:bg-brand-soft"
          >
            {content}
          </a>
        ) : (
          <span
            key={citation.id}
            className="inline-flex items-center gap-1.5 rounded-md bg-white px-2 py-1 text-[10px] font-medium text-slate-600 ring-1 ring-slate-200"
          >
            {content}
          </span>
        );
      })}
    </div>
  );
}

export function OrchestratorConversation({
  state,
  onSend,
  onUpload,
  onChooseOffer,
  disabled,
}: {
  state: ChatState;
  onSend: (text: string) => void;
  onUpload: (docType: string, file: File) => void;
  onChooseOffer: (offerId: string) => void;
  disabled: boolean;
}) {
  const lastAssistantIndex = lastAssistantEntryIndex(state);

  return (
    <div className="mx-auto max-w-[780px] space-y-6">
      <p className="text-center text-xs font-medium text-slate-500">
        YOUR CONVERSATION · SAVED LOCALLY
      </p>

      {state.latest && (
        <ProgressSteps progress={state.latest.progress} />
      )}

      {state.entries.map((entry, index) => {
        // Blocks belong to the latest assistant reply, even while a newer
        // customer message is pending or has failed.
        const isLastAssistant = index === lastAssistantIndex;

        return entry.role === "customer" ? (
          <div key={entry.id} className="flex justify-end">
            <div className="max-w-[85%] rounded-[20px] rounded-br-md bg-ink px-5 py-3 text-sm leading-relaxed text-white shadow-sm">
              {entry.text}
            </div>
          </div>
        ) : (
          <div key={entry.id}>
            <div className="flex gap-3">
              <AssistantAvatar small />
              <div className="min-w-0 flex-1 rounded-[20px] rounded-tl-md bg-slate-50 p-5">
                <p className="mb-2 text-xs font-semibold text-brand-ink">
                  LUMA · AI ASSISTANT
                </p>
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-700">
                  {entry.text}
                </p>
                <Citations citations={entry.citations} />
              </div>
            </div>
            {isLastAssistant && state.latest && (
              <div className="ml-12">
                <Blocks
                  latest={state.latest}
                  state={state}
                  onSend={onSend}
                  onUpload={onUpload}
                  onChooseOffer={onChooseOffer}
                  disabled={disabled}
                />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
