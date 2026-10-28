"use client";

// Adapted from shadcn/ui's MIT-licensed Dialog; Radix owns focus/keyboard behavior.
import type { ComponentProps } from "react";
import { Dialog as Primitive } from "radix-ui";
import { X } from "lucide-react";
import { cn } from "./utils";

export const Dialog = Primitive.Root;
export const DialogTrigger = Primitive.Trigger;
export const DialogClose = Primitive.Close;
export function DialogContent({ className, children, ...props }: ComponentProps<typeof Primitive.Content>) {
  return <Primitive.Portal><Primitive.Overlay className="fixed inset-0 z-50 bg-slate-950/45 backdrop-blur-sm data-[state=open]:animate-in data-[state=open]:fade-in-0" />
    <Primitive.Content className={cn("fixed left-1/2 top-1/2 z-50 grid max-h-[90dvh] w-[calc(100%_-_2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 gap-5 overflow-y-auto rounded-3xl border border-slate-200 bg-white p-7 shadow-2xl outline-none data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95", className)} {...props}>
      {children}<Primitive.Close aria-label="Close dialog" className="absolute right-5 top-5 rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700 focus-visible:ring-4 focus-visible:ring-primary/40"><X className="size-5" /></Primitive.Close>
    </Primitive.Content>
  </Primitive.Portal>;
}
export function DialogHeader(props: ComponentProps<"div">) { return <div {...props} className={cn("space-y-2 pr-5", props.className)} />; }
export function DialogTitle(props: ComponentProps<typeof Primitive.Title>) { return <Primitive.Title {...props} className={cn("text-xl font-semibold tracking-tight text-foreground", props.className)} />; }
export function DialogDescription(props: ComponentProps<typeof Primitive.Description>) { return <Primitive.Description {...props} className={cn("text-sm leading-relaxed text-muted-foreground", props.className)} />; }
export function DialogFooter(props: ComponentProps<"div">) { return <div {...props} className={cn("flex flex-wrap justify-end gap-3 pt-2", props.className)} />; }
