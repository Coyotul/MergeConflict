"use client";

import Link from "next/link";
import { ArrowRight, RefreshCw, TrendingDown } from "lucide-react";
import { PageHeading, Panel, InfoNote } from "@banking/ui/primitives";
import { Button } from "@banking/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@banking/ui/tabs";
import { LoanDetails } from "@/components/loan-details";
import { RepaymentSimulator } from "@/components/repayment-simulator";
import { RefinanceSimulator } from "@/components/refinance-simulator";

export default function LoansPage() {
  return <div className="mx-auto max-w-6xl"><PageHeading eyebrow="Your existing credit" title="Your loans, without the guesswork." description="Understand the synthetic balances, explore partial repayments and compare refinancing. No financial operation will be executed." action={<Button variant="outline" asChild><Link href="/?topic=details">Discuss my current loans<ArrowRight /></Link></Button>} /><Tabs defaultValue="overview"><TabsList aria-label="Loan tools"><TabsTrigger value="overview">Loan overview</TabsTrigger><TabsTrigger value="repayment"><TrendingDown className="mr-2 inline size-3.5" />Early repayment</TabsTrigger><TabsTrigger value="refinance"><RefreshCw className="mr-2 inline size-3.5" />Refinancing</TabsTrigger></TabsList><TabsContent value="overview"><div className="grid items-start gap-6 xl:grid-cols-[1.5fr_1fr]"><LoanDetails /><Panel><h2 className="mb-4 text-sm font-semibold">Thinking about a change?</h2><p className="text-xs leading-relaxed text-slate-500">A shorter term may save interest. A lower payment may improve cash flow but increase overall cost. Explore both before deciding.</p><div className="mt-5 space-y-3"><Button variant="secondary" className="w-full" asChild><Link href="/?topic=modify">Explore changes with Luma<ArrowRight /></Link></Button><InfoNote>Principal is not a settlement amount. For full early repayment, your bank must provide a date-specific authoritative quote.</InfoNote></div></Panel></div></TabsContent><TabsContent value="repayment"><div className="max-w-3xl"><RepaymentSimulator /></div></TabsContent><TabsContent value="refinance"><div className="max-w-3xl"><RefinanceSimulator /></div></TabsContent></Tabs></div>;
}
