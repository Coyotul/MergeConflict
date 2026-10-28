import type { Metadata } from "next";
import "@fontsource-variable/inter";
import "./globals.css";
import { DemoProvider } from "@banking/demo/react";
import { CustomerShell } from "@/components/customer-shell";

export const metadata: Metadata = { title: { default: "Luma · Your financial companion", template: "%s · Luma" }, description: "Local synthetic banking assistant prototype. Independent fictional brand; no real banking operations." };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body><DemoProvider role="customer"><CustomerShell>{children}</CustomerShell></DemoProvider></body></html>;
}
