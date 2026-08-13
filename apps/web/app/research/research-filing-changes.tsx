"use client";

import { FormEvent, useMemo, useState } from "react";

import type {
  FilingChange,
  FilingChangeEvidence,
  FilingChangeRun,
  ResearchDocument
} from "@/lib/api";


function errorMessage(payload: unknown, fallback: string) {
  if (!payload || typeof payload !== "object") return fallback;
  const detail = (payload as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object") {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === "string") return message.replaceAll("_", " ");
  }
  return fallback;
}


function documentLabel(document: ResearchDocument) {
  const period = document.fiscal_year ? `FY${document.fiscal_year}` : document.filing_date ?? "period unknown";
  return `${period} · ${document.filename}`;
}


function runPeriod(run: FilingChangeRun) {
  const older = run.older_fiscal_year ? `FY${run.older_fiscal_year}` : run.older_filing_date ?? "older";
  const newer = run.newer_fiscal_year ? `FY${run.newer_fiscal_year}` : run.newer_filing_date ?? "newer";
  return `${older} → ${newer}`;
}


function formatDate(value?: string | null) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(parsed);
}


function evidenceHref(evidence: FilingChangeEvidence) {
  const internal = `/research/documents/${encodeURIComponent(evidence.document_id)}/file`;
  if (evidence.page_number) return `${internal}#page=${evidence.page_number}`;
  return evidence.source_url || internal;
}


function EvidenceCard({ label, evidence }: { label: string; evidence: FilingChangeEvidence }) {
  return (
    <article className="filing-change-evidence">
      <div>
        <span>{label}</span>
        <strong>{evidence.fiscal_year ? `FY${evidence.fiscal_year}` : evidence.filing_date ?? "Filing"}</strong>
      </div>
      <blockquote>{evidence.quote}</blockquote>
      <a href={evidenceHref(evidence)} target="_blank" rel="noreferrer">
        {evidence.filename} · {evidence.locator} ↗
      </a>
    </article>
  );
}


export function ResearchFilingChanges({
  symbol,
  documents,
  initialRuns
}: {
  symbol: string;
  documents: ResearchDocument[];
  initialRuns: FilingChangeRun[];
}) {
  const [availableDocuments, setAvailableDocuments] = useState(documents);
  const comparableDocuments = useMemo(
    () => availableDocuments.filter((item) => item.status === "indexed" && item.document_type === "annual_report"),
    [availableDocuments]
  );
  const [runs, setRuns] = useState(initialRuns);
  const [activeRun, setActiveRun] = useState<FilingChangeRun | null>(null);
  const [olderDocumentId, setOlderDocumentId] = useState(comparableDocuments[1]?.id ?? "");
  const [newerDocumentId, setNewerDocumentId] = useState(comparableDocuments[0]?.id ?? "");
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [notes, setNotes] = useState<Record<string, string>>({});

  async function refreshDocuments() {
    try {
      const response = await fetch(`/research/documents?symbol=${encodeURIComponent(symbol)}`, { cache: "no-store" });
      const payload = await response.json();
      if (!response.ok || !Array.isArray(payload.documents)) return;
      const nextDocuments = payload.documents as ResearchDocument[];
      const comparable = nextDocuments.filter((item) => item.status === "indexed" && item.document_type === "annual_report");
      setAvailableDocuments(nextDocuments);
      if (!newerDocumentId && comparable[0]) setNewerDocumentId(comparable[0].id);
      if (!olderDocumentId && comparable[1]) setOlderDocumentId(comparable[1].id);
    } catch {
      // The existing list remains usable when a refresh cannot be completed.
    }
  }

  async function refreshRuns() {
    const response = await fetch(`/research/filing-changes?symbol=${encodeURIComponent(symbol)}`, { cache: "no-store" });
    const payload = await response.json();
    if (response.ok && Array.isArray(payload.runs)) setRuns(payload.runs as FilingChangeRun[]);
  }

  async function loadRun(runId: string) {
    const response = await fetch(`/research/filing-changes/${encodeURIComponent(runId)}`, { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) throw new Error(errorMessage(payload, "Filing change result unavailable"));
    const result = payload as FilingChangeRun;
    setActiveRun(result);
    setRuns((current) => [result, ...current.filter((item) => item.id !== result.id)]);
    return result;
  }

  async function pollRun(runId: string) {
    for (let attempt = 0; attempt < 300; attempt += 1) {
      const result = await loadRun(runId);
      if (["completed", "failed"].includes(result.status)) {
        await refreshRuns();
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }
    throw new Error("The run is still processing. It remains in history and can be reopened later.");
  }

  async function start(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (working) return;
    if (!olderDocumentId || !newerDocumentId || olderDocumentId === newerDocumentId) {
      setError("Select two different indexed annual reports.");
      return;
    }
    setWorking(true);
    setError("");
    setActiveRun(null);
    try {
      const response = await fetch("/research/filing-changes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol,
          older_document_id: olderDocumentId,
          newer_document_id: newerDocumentId,
          max_changes: 24
        })
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(errorMessage(payload, "Filing change run could not be queued"));
      await pollRun(String(payload.id));
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : "Filing change run failed");
    } finally {
      setWorking(false);
    }
  }

  async function rerun() {
    if (!activeRun || working) return;
    setWorking(true);
    setError("");
    try {
      const response = await fetch(`/research/filing-changes/${encodeURIComponent(activeRun.id)}/rerun`, {
        method: "POST"
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(errorMessage(payload, "Rerun could not be queued"));
      await pollRun(String(payload.id));
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : "Rerun failed");
    } finally {
      setWorking(false);
    }
  }

  async function review(change: FilingChange, decision: "confirmed" | "rejected" | "needs_edit") {
    setError("");
    try {
      const response = await fetch(
        `/research/filing-changes/changes/${encodeURIComponent(change.id)}/review`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ decision, note: notes[change.id] || null })
        }
      );
      const payload = await response.json();
      if (!response.ok) throw new Error(errorMessage(payload, "Review could not be saved"));
      if (activeRun) await loadRun(activeRun.id);
    } catch (reviewError) {
      setError(reviewError instanceof Error ? reviewError.message : "Review could not be saved");
    }
  }

  return (
    <section className="filing-change-panel">
      <div className="research-section-heading">
        <div>
          <h2>Compare Annual Filings</h2>
        </div>
        <span>{runs.length}</span>
      </div>

      <div className="filing-change-content">
        <form className="filing-change-form" onSubmit={start}>
          <label>
            <span>Older filing</span>
            <select value={olderDocumentId} onFocus={() => void refreshDocuments()} onChange={(event) => setOlderDocumentId(event.target.value)}>
              <option value="">Select indexed annual report</option>
              {comparableDocuments.map((document) => (
                <option key={document.id} value={document.id}>{documentLabel(document)}</option>
              ))}
            </select>
          </label>
          <span className="filing-change-arrow">→</span>
          <label>
            <span>Newer filing</span>
            <select value={newerDocumentId} onFocus={() => void refreshDocuments()} onChange={(event) => setNewerDocumentId(event.target.value)}>
              <option value="">Select indexed annual report</option>
              {comparableDocuments.map((document) => (
                <option key={document.id} value={document.id}>{documentLabel(document)}</option>
              ))}
            </select>
          </label>
          <button type="submit" disabled={working || comparableDocuments.length < 2}>
            {working ? "Comparing filings…" : "Run change detection"}
          </button>
        </form>

        {comparableDocuments.length < 2 ? (
          <p className="research-document-empty">
            At least two indexed annual reports are required. Sync two SEC 10-K filings or upload two annual-report PDFs.
          </p>
        ) : null}
        {error ? <p className="research-error" role="alert">{error}</p> : null}

        {runs.length ? (
          <div className="filing-change-history">
            <div>
              <strong>Run history</strong>
              <small>Versioned · reviewable</small>
            </div>
            <div className="filing-change-run-list">
              {runs.map((run) => (
                <button key={run.id} type="button" onClick={() => void loadRun(run.id)} className={activeRun?.id === run.id ? "is-active" : undefined}>
                  <span>{runPeriod(run)}</span>
                  <strong>{run.status}</strong>
                  <small>{run.result_count} changes · {run.reviewed_count ?? 0} reviewed · {formatDate(run.created_at)}</small>
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {activeRun ? (
          <div className="filing-change-result">
            <div className="filing-change-result-head">
              <div>
                <span className={`filing-change-status is-${activeRun.status}`}>{activeRun.status}</span>
                <strong>{runPeriod(activeRun)}</strong>
                <small>{activeRun.algorithm_version} · run {activeRun.id.slice(0, 8)}</small>
              </div>
              <button type="button" onClick={rerun} disabled={working || activeRun.status === "queued" || activeRun.status === "running"}>
                Rerun as new history
              </button>
            </div>
            {activeRun.status === "failed" ? (
              <p className="research-error">{activeRun.error_message || activeRun.error_code || "Change detection failed"}</p>
            ) : null}
            {["queued", "running"].includes(activeRun.status) ? (
              <p className="filing-change-progress">The worker is matching both filings and calculating material changes…</p>
            ) : null}
            {activeRun.status === "completed" && !activeRun.changes?.length ? (
              <p className="research-document-empty">No changes passed the saved materiality threshold for this run.</p>
            ) : null}
            <div className="filing-change-list">
              {activeRun.changes?.map((change) => (
                <article className="filing-change-card" key={change.id}>
                  <div className="filing-change-card-head">
                    <div>
                      <span className={`filing-change-type is-${change.change_type}`}>{change.change_type}</span>
                      <strong>{change.summary}</strong>
                    </div>
                    <div>
                      <span>Materiality {(change.materiality_score * 100).toFixed(0)}%</span>
                      <span>Similarity {(change.similarity_score * 100).toFixed(0)}%</span>
                    </div>
                  </div>
                  <div className="filing-change-evidence-grid">
                    <EvidenceCard label="Older filing evidence" evidence={change.older_evidence} />
                    <EvidenceCard label="Newer filing evidence" evidence={change.newer_evidence} />
                  </div>
                  <p className="filing-change-rationale">{change.rationale}</p>
                  <div className="filing-change-review">
                    <div>
                      <strong>Human review</strong>
                      <span className={`is-${change.review_status}`}>{change.review_status.replaceAll("_", " ")}</span>
                      {change.review_history?.length ? <small>{change.review_history.length} recorded decision(s)</small> : null}
                    </div>
                    <input
                      value={notes[change.id] ?? ""}
                      onChange={(event) => setNotes((current) => ({ ...current, [change.id]: event.target.value }))}
                      placeholder="Optional reviewer note"
                      maxLength={2000}
                    />
                    <div>
                      <button type="button" onClick={() => void review(change, "confirmed")}>Confirm</button>
                      <button type="button" onClick={() => void review(change, "needs_edit")}>Needs edit</button>
                      <button type="button" onClick={() => void review(change, "rejected")}>Reject</button>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          </div>
        ) : null}

        <p className="filing-change-method">
          Results are candidates, not conclusions. The saved run uses reciprocal semantic matching plus versioned,
          deterministic language-strength and materiality rules. Every item remains pending until human review.
        </p>
      </div>
    </section>
  );
}
