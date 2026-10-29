"use client";

import { useEffect, useRef, useState } from "react";
import { LoaderCircle, MessageCircle, RotateCcw, ShieldCheck } from "lucide-react";
import { useDemo } from "@banking/demo/react";
import { useOrchestratorChat } from "@banking/demo/orchestrator-react";
import { hasCustomerMessages, retryNotice } from "@banking/demo/orchestrator-state";
import { AssistantAvatar, InfoNote, PilotNotice } from "@banking/ui/primitives";
import { Button } from "@banking/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@banking/ui/dialog";
import { StartingCards } from "./guided-options";
import { Composer } from "./composer";
import { OrchestratorConversation } from "./orchestrator/conversation";
import { QuickSuggestions } from "./orchestrator/quick-suggestions";

const TOPIC_QUERIES: Record<string, string> = {
  support: "I need human support",
  repayment: "I want to simulate early repayment",
  refinance: "I want to explore refinancing",
  loan: "I want a loan",
  modify: "Change my current loan",
  details: "My current loan details",
  personal: "I want a personal loan",
  mortgage: "I want a mortgage",
  car: "I want a car loan",
};

export function AssistantWorkspace() {
  const { snapshot } = useDemo();
  const { state, send, upload, chooseOffer, confirm, retry, restart } = useOrchestratorChat(snapshot?.customer.id);
  const [ending, setEnding] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  const topicRead = useRef(false);
  const topicText = useRef<string | null>(null);
  const count = state.entries.length;

  useEffect(() => {
    if (count > 0) bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [count, state.pending]);

  // ?topic= deep links (dashboard, products, loans): read once, then send once the session exists.
  useEffect(() => {
    if (!snapshot) return;
    if (!topicRead.current) {
      topicRead.current = true;
      const topic = new URLSearchParams(window.location.search).get("topic");
      if (topic) {
        window.history.replaceState({}, "", "/");
        topicText.current = TOPIC_QUERIES[topic] ?? null;
      }
    }
    if (!topicText.current || !state.sessionId || state.pending) return;
    const text = topicText.current;
    topicText.current = null;
    void send(text);
  }, [snapshot, state.sessionId, state.pending, send]);

  if (!snapshot) return null;
  const welcome = !hasCustomerMessages(state);
  const disabled = state.pending || !state.sessionId;
  const onSend = (text: string) => { void send(text); };
  // A failed confirmation is never replayed automatically: the summary stays visible
  // and the customer presses Confirm again.
  const notice = retryNotice(state);

  return (
    <div className="flex h-full min-h-0 flex-1 overflow-hidden">
      <div className="flex h-full min-w-0 flex-1 flex-col min-h-0 overflow-hidden">
        {/* Assistant Header */}
        <div className="flex shrink-0 items-center justify-between border-b border-slate-100 px-6 py-3 lg:px-8">
          <div className="flex items-center gap-3">
            <AssistantAvatar small />
            <div>
              <p className="text-sm font-semibold">Luma assistant</p>
              <p className="mt-0.5 flex items-center gap-1.5 text-xs text-slate-500">
                <span className="size-1.5 rounded-full bg-emerald-500" />
                Your financial companion · AI assistant
              </p>
            </div>
          </div>
          <Button variant="link" size="sm" disabled={state.pending || welcome} onClick={() => setEnding(true)}>
            End chat
          </Button>
        </div>

        {/* Scrollable Conversation Container */}
        <div className="conversation-scroll min-h-0 flex-1 overflow-y-auto px-6 py-4 lg:px-8">
          {welcome ? (
            <div className="mx-auto flex max-w-[830px] flex-col justify-center min-h-full py-2">
              <div className="mb-5">
                <p className="mb-1.5 text-xs font-medium text-slate-500">A little help. A lot more clarity.</p>
                <h1 className="text-2xl font-semibold tracking-tight text-ink lg:text-3xl">
                  Hey {snapshot.customer.name.split(" ")[0]}, how can I help you <span className="greeting-highlight">today?</span>
                  <span className="blink-cursor" aria-hidden="true" />
                </h1>
                <p className="mt-2 text-xs text-slate-600">Pick a starting point, or simply ask me below.</p>
              </div>
              <StartingCards disabled={disabled} onSelect={onSend} />
              <div className="mt-4 flex items-center gap-2 text-xs text-slate-500">
                <MessageCircle className="size-3.5 text-slate-400" />
                One conversation. Every step of your credit journey.
              </div>
            </div>
          ) : (
            <OrchestratorConversation
              state={state}
              onSend={onSend}
              onUpload={(docType, file) => { void upload(docType, file); }}
              onChooseOffer={(offerId) => { void chooseOffer(offerId); }}
              onConfirm={(summaryVersion, decision) => { void confirm(summaryVersion, decision); }}
              disabled={disabled}
            />
          )}
          {state.pending && (
            <div role="status" className="mx-auto mt-6 flex max-w-[780px] items-center gap-2 text-xs text-slate-500">
              <LoaderCircle className="size-4 animate-spin text-slate-400" />
              Luma is thinking…
            </div>
          )}
          {state.error && !state.pending && (
            <div className="mx-auto mt-6 max-w-[780px]" role="alert">
              <InfoNote warning>
                <span className="flex flex-wrap items-center gap-3">
                  <span>{state.error.message}</span>
                  {notice && <span>{notice}</span>}
                  {state.error.retryable && !notice && (
                    <Button variant="outline" size="sm" onClick={() => { void retry(); }}>
                      <RotateCcw />Retry
                    </Button>
                  )}
                </span>
              </InfoNote>
            </div>
          )}
          <div ref={bottom} />
        </div>

        {/* Pinned Composer Footer */}
        <div className="shrink-0 border-t border-slate-100 bg-white px-6 pb-4 pt-3 lg:px-8">
          <div className="mx-auto max-w-[830px]">
            {welcome ? (
              <div className="mb-3">
                <PilotNotice />
              </div>
            ) : (
              <>
                <div className="mb-1.5 flex items-center justify-end gap-3">
                  <span className="flex items-center gap-1.5 text-xs text-slate-500">
                    <ShieldCheck className="size-3.5 text-slate-400" />Synthetic data · simulated, based on public conditions
                  </span>
                </div>
                <QuickSuggestions
                  state={state}
                  disabled={disabled}
                  onSelect={(val) => {
                    void send(val);
                  }}
                />
              </>
            )}
            <Composer disabled={disabled} onSend={send} />
          </div>
        </div>
      </div>
      <Dialog open={ending} onOpenChange={setEnding}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Start a fresh conversation?</DialogTitle>
            <DialogDescription>This starts a new assistant conversation. Your synthetic loan applications, documents and history remain saved locally.</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEnding(false)}>Keep chatting</Button>
            <Button onClick={() => { restart(); setEnding(false); }}>End chat & start fresh</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
