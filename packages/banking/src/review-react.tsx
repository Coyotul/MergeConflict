"use client";

import { useCallback, useEffect, useState } from "react";
import { listMyApplications, type CustomerApplication } from "./review-api";

const POLL_MS = 5000;

/** The signed-in customer's submitted applications, refreshed every few seconds. */
export function useMyApplications(customerId: string | undefined) {
  const [applications, setApplications] = useState<CustomerApplication[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(async () => {
    if (!customerId) return;
    try {
      setApplications(await listMyApplications(customerId));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The application service is unavailable.");
    }
  }, [customerId]);
  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, POLL_MS);
    return () => clearInterval(timer);
  }, [refresh]);
  return { applications, error, refresh };
}
