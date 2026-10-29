"use client";

import { useCallback, useEffect, useState } from "react";
import { listMyApplications, listQueue, type CustomerApplication, type QueueItem } from "./review-api";

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

/** The reviewer queue, refreshed every few seconds. */
export function useReviewQueue() {
  const [queue, setQueue] = useState<QueueItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const load = () => listQueue().then((q) => { setQueue(q); setError(null); })
      .catch((e) => setError(e instanceof Error ? e.message : "The review service is unavailable."));
    load();
    const timer = setInterval(load, POLL_MS);
    return () => clearInterval(timer);
  }, []);
  return { queue, error };
}
