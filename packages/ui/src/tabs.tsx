"use client";

import type { ComponentProps } from "react";
import { Tabs as Primitive } from "radix-ui";
import { cn } from "./utils";

export const Tabs = Primitive.Root;
export function TabsList(props: ComponentProps<typeof Primitive.List>) { return <Primitive.List {...props} className={cn("inline-flex flex-wrap gap-1 rounded-xl bg-slate-100 p-1", props.className)} />; }
export function TabsTrigger(props: ComponentProps<typeof Primitive.Trigger>) { return <Primitive.Trigger {...props} className={cn("rounded-lg px-4 py-2 text-sm font-medium text-slate-500 transition-colors focus-visible:ring-4 focus-visible:ring-primary/40 data-[state=active]:bg-primary data-[state=active]:text-primary-foreground data-[state=active]:shadow-sm", props.className)} />; }
export function TabsContent(props: ComponentProps<typeof Primitive.Content>) { return <Primitive.Content {...props} className={cn("mt-5 outline-none focus-visible:ring-4 focus-visible:ring-primary/25", props.className)} />; }
