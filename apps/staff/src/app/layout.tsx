import type { Metadata } from "next";
import "@fontsource-variable/inter";
import "./globals.css";
import { DemoProvider } from "@banking/demo/react";
import { StaffShell } from "@/components/staff-shell";

export const metadata: Metadata = { title: "Luma · Bank agent workspace", description: "Independent human review of synthetic loan applications. Local prototype only; not affiliated with any bank." };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body><DemoProvider role="reviewer"><StaffShell>{children}</StaffShell></DemoProvider></body></html>;
}
