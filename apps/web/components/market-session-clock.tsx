"use client";

import { useCallback, useEffect, useState } from "react";

import type { MarketSession } from "@/lib/api";


function formatClock(timestamp: number, timeZone: string) {
  if (!timestamp) return "—";
  return new Intl.DateTimeFormat("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone,
    timeZoneName: "short"
  }).format(new Date(timestamp));
}

function formatCountdown(now: number, target: string | null) {
  if (!target) return "";
  const remainingMinutes = Math.max(0, Math.ceil((Date.parse(target) - now) / 60_000));
  const days = Math.floor(remainingMinutes / 1_440);
  const hours = Math.floor((remainingMinutes % 1_440) / 60);
  const minutes = remainingMinutes % 60;
  if (days) return `${days}d ${hours}h`;
  if (hours) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

export function MarketSessionClock({
  initialSession,
  refreshEndpoint = "/api/us/session"
}: {
  initialSession: MarketSession | null;
  refreshEndpoint?: string;
}) {
  const [session, setSession] = useState(initialSession);
  const [now, setNow] = useState(() => Date.parse(initialSession?.observed_at ?? "") || 0);

  const refresh = useCallback(async () => {
    try {
      const response = await fetch(refreshEndpoint, { cache: "no-store" });
      if (!response.ok) return;
      const next = await response.json() as MarketSession;
      setSession(next);
    } catch {
      // Keep the last confirmed session state during a transient refresh failure.
    }
  }, [refreshEndpoint]);

  useEffect(() => {
    setNow(Date.now());
    const clock = window.setInterval(() => setNow(Date.now()), 30_000);
    const sync = window.setInterval(refresh, 60_000);
    return () => {
      window.clearInterval(clock);
      window.clearInterval(sync);
    };
  }, [refresh]);

  useEffect(() => {
    if (session?.next_transition_at && now >= Date.parse(session.next_transition_at)) void refresh();
  }, [now, refresh, session?.next_transition_at]);

  const countdown = formatCountdown(now, session?.next_transition_at ?? null);
  const transition = session?.next_transition && countdown
    ? `${session.next_transition} in ${countdown}`
    : "schedule unavailable";

  return (
    <span className={`market-session-clock is-${session?.status ?? "unknown"}`}>
      <span className="market-session-title">
        <span className="market-session-dot" aria-hidden="true" />
        <strong>{session?.label ?? "US Market"}</strong>
      </span>
      <span className="market-session-detail">
        <time>{formatClock(now, session?.timezone ?? "America/New_York")}</time>
        <span aria-hidden="true">·</span>
        <span>{transition}</span>
      </span>
    </span>
  );
}
