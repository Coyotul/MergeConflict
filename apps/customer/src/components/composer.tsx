"use client";

import { useEffect, useRef, useState } from "react";
import { CornerDownLeft, Paperclip, SendHorizontal } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@banking/ui/dialog";
import { Button } from "@banking/ui/button";
import { ApplicationCard } from "./application-card";
import { useDemo } from "@banking/demo/react";

export function Composer({ onSend, disabled }: { onSend: (text: string) => Promise<boolean>; disabled: boolean }) {
  const [text, setText] = useState("");
  const [documents, setDocuments] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { snapshot } = useDemo();
  const active = snapshot?.applications.find((a) =>
    ["AWAITING_DOCUMENTS", "MORE_INFORMATION_REQUIRED", "READY_FOR_SUBMISSION"].includes(a.status)
  );

  const adjustHeight = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    const nextHeight = Math.min(el.scrollHeight, 140);
    el.style.height = `${Math.max(nextHeight, 38)}px`;
  };

  useEffect(() => {
    adjustHeight();
  }, [text]);

  async function submit() {
    if (text.trim() && !disabled && (await onSend(text.trim()))) {
      setText("");
    }
  }

  return (
    <>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
        className="flex items-end gap-3"
      >
        <div className="flex min-w-0 flex-1 items-end rounded-[22px] border border-transparent bg-slate-100 px-3 py-1.5 focus-within:border-brand-border/60 focus-within:bg-white focus-within:ring-4 focus-within:ring-primary/20">
          <button
            type="button"
            disabled={disabled}
            onClick={() => setDocuments(true)}
            aria-label="Open document checklist"
            className="mb-1 rounded-full p-2 text-slate-500 transition-colors hover:bg-slate-200/60 hover:text-brand-ink"
          >
            <Paperclip className="size-5" strokeWidth={1.7} />
          </button>
          <textarea
            ref={textareaRef}
            aria-label="Message the assistant"
            placeholder="Tell me what's on your mind…"
            rows={1}
            maxLength={2000}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void submit();
              }
            }}
            className="max-h-36 min-h-[38px] w-full resize-none overflow-y-auto bg-transparent px-2 py-1.5 text-sm leading-6 text-slate-800 outline-none placeholder:text-slate-400 focus-visible:outline-none"
          />
          <span className="mb-2 mr-1 hidden text-slate-300 2xl:inline">
            <CornerDownLeft className="size-4" />
          </span>
        </div>
        <button
          type="submit"
          disabled={disabled || !text.trim()}
          aria-label="Send message"
          className="flex size-12 shrink-0 items-center justify-center rounded-full bg-primary text-ink shadow-sm transition-transform active:scale-95 hover:bg-primary/90 disabled:opacity-40"
        >
          <SendHorizontal className="size-5" strokeWidth={1.7} />
        </button>
      </form>
      <p className="mt-2 text-center text-xs text-slate-500">
        Your own words are always welcome. Enter to send · Shift + Enter for a new line.
      </p>
      <Dialog open={documents} onOpenChange={setDocuments}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>Your document checklist</DialogTitle>
            <DialogDescription>
              Only synthetic file metadata is stored. No file contents are uploaded or verified.
            </DialogDescription>
          </DialogHeader>
          {active ? (
            <ApplicationCard application={active} />
          ) : (
            <div className="rounded-2xl bg-slate-50 p-5">
              <p className="text-sm font-semibold">No draft is waiting for documents.</p>
              <p className="mt-2 text-xs leading-relaxed text-slate-600">
                Choose a loan scenario first. Documents belong to a specific application; never attach real banking files to the conversation.
              </p>
              <Button
                variant="secondary"
                size="sm"
                className="mt-4"
                onClick={() => {
                  setDocuments(false);
                  void onSend("I want a loan");
                }}
              >
                Explore a loan scenario
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
