"use client";

import { useEffect, useRef, useState } from "react";
import { CornerDownLeft, SendHorizontal } from "lucide-react";

export function Composer({ onSend, disabled }: { onSend: (text: string) => Promise<boolean>; disabled: boolean }) {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

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
    </>
  );
}
