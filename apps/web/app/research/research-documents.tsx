"use client";

import { FormEvent, useState } from "react";

import type { ResearchDocument } from "@/lib/api";


function statusLabel(status: string) {
  if (status === "uploaded") return "Queued";
  if (status === "processing") return "Extracting pages";
  if (status === "text_ready") return "Page text ready";
  if (status === "indexed") return "Search ready";
  if (status === "failed") return "Failed";
  return status.replaceAll("_", " ");
}


function formatBytes(value: number) {
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}


export function ResearchDocuments({
  symbol,
  initialDocuments
}: {
  symbol: string;
  initialDocuments: ResearchDocument[];
}) {
  const [documents, setDocuments] = useState(initialDocuments);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");

  function upsertDocument(document: ResearchDocument) {
    setDocuments((current) => [document, ...current.filter((item) => item.id !== document.id)]);
  }

  async function pollDocument(documentId: string) {
    for (let attempt = 0; attempt < 40; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 1000));
      const response = await fetch(`/research/documents/${encodeURIComponent(documentId)}`, {
        cache: "no-store"
      });
      if (!response.ok) return;
      const document = await response.json() as ResearchDocument;
      upsertDocument(document);
      if (["text_ready", "indexed", "failed"].includes(document.status)) return;
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (uploading) return;
    const form = event.currentTarget;
    const payload = new FormData(form);
    const file = payload.get("file");
    if (!(file instanceof File) || file.size === 0) {
      setError("Choose a PDF before uploading.");
      return;
    }
    payload.set("symbol", symbol);
    if (!String(payload.get("fiscal_year") ?? "").trim()) payload.delete("fiscal_year");

    setUploading(true);
    setError("");
    try {
      const response = await fetch("/research/documents", { method: "POST", body: payload });
      const result = await response.json();
      if (!response.ok) {
        const detail = typeof result?.detail === "string" ? result.detail : result?.detail?.message;
        throw new Error(detail || "Document upload failed");
      }
      const document = result as ResearchDocument;
      upsertDocument(document);
      form.reset();
      if (!["text_ready", "indexed", "failed"].includes(document.status)) {
        void pollDocument(document.id);
      }
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : "Document upload failed");
    } finally {
      setUploading(false);
    }
  }

  return (
    <section className="research-documents-panel">
      <div className="research-section-heading">
        <div>
          <p className="research-kicker">Source documents</p>
          <h2>{symbol} filing workspace</h2>
        </div>
        <span>{documents.length}</span>
      </div>

      <div className="research-documents-content">
        <form className="research-document-upload" onSubmit={submit}>
          <label>
            <span>PDF document</span>
            <input name="file" type="file" accept="application/pdf,.pdf" required />
          </label>
          <label>
            <span>Document type</span>
            <select name="document_type" defaultValue="annual_report">
              <option value="annual_report">Annual report</option>
              <option value="quarterly_report">Quarterly report</option>
              <option value="earnings_release">Earnings release</option>
              <option value="proxy_statement">Proxy statement</option>
              <option value="other">Other filing</option>
            </select>
          </label>
          <label>
            <span>Fiscal year</span>
            <input name="fiscal_year" type="number" min="1990" max="2100" placeholder="2025" />
          </label>
          <button type="submit" disabled={uploading}>
            {uploading ? "Uploading…" : "Upload & extract pages"}
          </button>
        </form>

        {error ? <p className="research-error" role="alert">{error}</p> : null}

        <div className="research-document-list">
          {documents.map((document) => (
            <article key={document.id}>
              <div>
                <strong>{document.filename}</strong>
                <small>{document.document_type.replaceAll("_", " ")} · {formatBytes(document.size_bytes)}</small>
              </div>
              <div className="research-document-stats">
                <span>{document.page_count ?? "—"} pages</span>
                <span>{document.chunk_count} chunks</span>
              </div>
              <span className={`research-document-status is-${document.status}`}>
                {statusLabel(document.status)}
              </span>
              {document.error_message ? <p>{document.error_message}</p> : null}
            </article>
          ))}
          {documents.length === 0 ? (
            <p className="research-document-empty">
              No company documents yet. Upload a PDF to preserve page-level evidence for retrieval.
            </p>
          ) : null}
        </div>
      </div>
    </section>
  );
}
