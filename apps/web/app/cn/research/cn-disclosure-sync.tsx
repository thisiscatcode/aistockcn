"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function CnDisclosureSync({ symbol }: { symbol: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  async function sync() {
    if (busy) return;
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch("/research/documents/cn", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol, document_types: ["annual_report", "semiannual_report", "quarterly_report"], years: 3, limit_per_type: 2 })
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result?.detail?.message || result?.detail || "Sync failed");
      setMessage(`${result.queued ?? 0} filing${result.queued === 1 ? "" : "s"} queued${result.duplicates ? ` · ${result.duplicates} already present` : ""}.`);
      router.refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Sync failed");
    } finally {
      setBusy(false);
    }
  }
  return <div className="cn-sync-control"><button type="button" onClick={sync} disabled={busy}>{busy ? "Syncing official filings…" : "Sync official filings"}</button>{message ? <span role="status">{message}</span> : null}</div>;
}
