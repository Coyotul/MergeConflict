"use client";

import type { ComponentProps } from "react";
import { Switch as Primitive } from "radix-ui";
import { cn } from "./utils";

export function Switch(props: ComponentProps<typeof Primitive.Root>) {
  return <Primitive.Root {...props} className={cn("inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-primary/40 disabled:opacity-50 data-[state=checked]:bg-ink data-[state=unchecked]:bg-slate-200", props.className)}>
    <Primitive.Thumb className="pointer-events-none block size-5 rounded-full bg-white shadow-sm transition-transform data-[state=checked]:translate-x-5 data-[state=checked]:bg-primary data-[state=unchecked]:translate-x-0" />
  </Primitive.Root>;
}
