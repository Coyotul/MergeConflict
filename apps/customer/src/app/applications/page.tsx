"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { useDemo } from "@banking/demo/react";
import { useMyApplications } from "@banking/demo/review-react";
import { Button } from "@banking/ui/button";
import { EmptyState, InfoNote, PageHeading } from "@banking/ui/primitives";
import { ReviewApplicationCard } from "@/components/review-application-card";

const FINAL = ["APPROVED", "REJECTED"];

export default function ApplicationsPage() {
  const { snapshot } = useDemo();
  const customerId = snapshot?.customer.id;
  const { applications, error, refresh } = useMyApplications(customerId);
  const [filter, setFilter] = useState("all");
  if (!customerId) return null;
  const shown = (applications ?? []).filter((a) => filter === "all" || (filter === "active" ? !FINAL.includes(a.status) : FINAL.includes(a.status)));
  return (
    <div className="mx-auto max-w-6xl">
      <PageHeading eyebrow="Every step, kept in view" title="Your applications."
        description="Applications you submit through the assistant appear here. A human reviewer decides each one; if they need another document, you can send it from this page."
        action={<Button asChild><Link href="/?topic=loan">Explore a new loan<ArrowRight /></Link></Button>} />
      <div className="mb-6 flex gap-2" role="group" aria-label="Filter applications">
        {["all", "active", "completed"].map((f) => (
          <Button key={f} size="sm" variant={filter === f ? "default" : "outline"} onClick={() => setFilter(f)} aria-pressed={filter === f}>
            {f.charAt(0).toUpperCase() + f.slice(1)}
          </Button>
        ))}
      </div>
      {error && <div className="mb-6"><InfoNote warning>{error}</InfoNote></div>}
      {applications === null && !error ? null : shown.length ? (
        <div className="space-y-7">
          {shown.map((app) => <ReviewApplicationCard key={app.id} application={app} customerId={customerId} onChange={refresh} />)}
        </div>
      ) : (
        <EmptyState title="No applications in this view.">Submit an application through the assistant and follow its review here.</EmptyState>
      )}
    </div>
  );
}
