"use client";

// Adapted from shadcn/ui's MIT-licensed Button using the unified Radix package.
import type { ComponentProps } from "react";
import { Slot } from "radix-ui";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "./utils";

const buttonVariants = cva("inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-xl text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-primary/40 disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0", {
  variants: {
    variant: { default: "bg-primary text-primary-foreground hover:bg-primary/80", destructive: "bg-red-600 text-white hover:bg-red-700", outline: "border border-slate-200 bg-white text-foreground hover:border-slate-400 hover:bg-slate-50", secondary: "bg-brand-soft text-foreground hover:bg-primary/35", ghost: "text-slate-600 hover:bg-slate-100 hover:text-foreground", link: "text-foreground decoration-brand-border decoration-2 underline-offset-4 hover:underline" },
    size: { default: "h-11 px-5", sm: "h-9 rounded-lg px-3 text-xs", lg: "h-12 px-7", icon: "size-10 p-0" },
  }, defaultVariants: { variant: "default", size: "default" },
});
export function Button({ className, variant, size, asChild = false, ...props }: ComponentProps<"button"> & VariantProps<typeof buttonVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : "button";
  return <Comp className={cn(buttonVariants({ variant, size, className }))} {...props} />;
}
export { buttonVariants };
