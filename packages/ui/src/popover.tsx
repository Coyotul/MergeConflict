"use client";

import type { ComponentProps } from "react";
import { Popover as Primitive } from "radix-ui";
import { cn } from "./utils";

export const Popover = Primitive.Root;
export const PopoverTrigger = Primitive.Trigger;
export function PopoverContent(props: ComponentProps<typeof Primitive.Content>) {
  return <Primitive.Portal><Primitive.Content sideOffset={10} align="end" {...props} className={cn("z-40 w-96 max-w-[calc(100vw-2rem)] rounded-2xl border border-slate-200 bg-white p-5 shadow-xl outline-none", props.className)} /></Primitive.Portal>;
}
