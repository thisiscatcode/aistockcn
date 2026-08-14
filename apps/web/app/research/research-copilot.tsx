"use client";

import { FormEvent, useState } from "react";

import type { ResearchAnswer } from "@/lib/api";


const SUGGESTIONS = [
  { label: "Investment summary", question: "Generate an investment research summary covering revenue, profitability, risks, management outlook and current market signals." },
  { label: "What changed?", question: "What changed in revenue, profit, risk language and management outlook across the available reports?" },
  { label: "Market performance", question: "What changed over the last month, and how volatile has the stock been?" },
  { label: "Evidence check", question: "Which conclusions are directly supported by the current evidence?" }
];


function sourceLabel(item: ResearchAnswer["data_evidence"][number]) {
  return `${item.source} · ${item.locator}`;
}

function researchErrorMessage(error: unknown) {
  const message = error instanceof Error ? error.message : String(error ?? "");
  if (message.includes("research_model_unavailable") || message.includes("research_model_invalid_response")) {
    return "The analysis model took too long. Your evidence is safe — try again.";
  }
  if (message.includes("company_not_found")) {
    return "This company is not available in the research universe.";
  }
  if (
    message.includes("research_internal_error") ||
    message.includes("Research stream ended") ||
    message.toLowerCase().includes("network") ||
    message.toLowerCase().includes("fetch")
  ) {
    return "The research connection was interrupted. Try again.";
  }
  return message || "Research could not be completed. Try again.";
}


export function ResearchCopilot({ symbol, initialQuestion = "" }: { symbol: string; initialQuestion?: string }) {
  const [question, setQuestion] = useState(initialQuestion);
  const [answer, setAnswer] = useState<ResearchAnswer | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState("");

  async function submit(event?: FormEvent) {
    event?.preventDefault();
    const cleanQuestion = question.trim();
    if (!cleanQuestion || loading) return;
    setLoading(true);
    setError("");
    setProgress("Starting research agent…");
    try {
      const response = await fetch("/research/ask/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({ symbol, question: cleanQuestion })
      });
      if (!response.ok || !response.body) {
        const payload = await response.json().catch(() => null);
        const detail = payload?.detail;
        const code = typeof detail === "object" && detail ? detail.code : detail;
        throw new Error(typeof code === "string" ? code : "Unable to run research agent");
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let completed = false;
      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value, { stream: !done });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";
        for (const frame of frames) {
          const event = frame.split("\n").find((line) => line.startsWith("event:"))?.slice(6).trim();
          const data = frame.split("\n").find((line) => line.startsWith("data:"))?.slice(5).trim();
          if (!event || !data) continue;
          const payload = JSON.parse(data);
          if (event === "status") setProgress(String(payload.message ?? payload.stage ?? "Running agent…"));
          if (event === "plan") setProgress(`Plan: ${(payload.tools ?? []).join(" → ")}`);
          if (event === "tool") setProgress(`Completed: ${String(payload.tool ?? "tool").replaceAll("_", " ")}`);
          if (event === "error") throw new Error(String(payload.code ?? payload.message ?? "Unable to run research agent"));
          if (event === "result") {
            setAnswer(payload as ResearchAnswer);
            completed = true;
          }
        }
        if (done) break;
      }
      if (!completed) throw new Error("Research stream ended before a result was returned");
    } catch (requestError) {
      setError(researchErrorMessage(requestError));
    } finally {
      setLoading(false);
      setProgress("");
    }
  }

  return (
    <section className="research-copilot-panel">
      <div className="research-section-heading">
        <div>
          <h2>Ask {symbol}</h2>
        </div>
        <span className="research-beta-badge">Cited</span>
      </div>

      <div className="research-suggestions">
        {SUGGESTIONS.map((suggestion) => (
          <button key={suggestion.label} type="button" onClick={() => setQuestion(suggestion.question)}>
            {suggestion.label}
          </button>
        ))}
      </div>

      <form className="research-question-form" onSubmit={submit}>
        <label className="sr-only" htmlFor="research-question">Research question</label>
        <textarea
          id="research-question"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Ask about revenue, margins, risks or guidance"
          maxLength={800}
          rows={2}
        />
        <div>
          <button type="submit" disabled={loading || !question.trim()}>
            {loading ? "Researching…" : "Ask"}
          </button>
        </div>
      </form>

      {loading && progress ? (
        <div className="research-agent-progress" role="status">
          <span className="research-agent-progress-spinner" aria-hidden="true" />
          <span>{progress}</span>
        </div>
      ) : null}

      {error ? (
        <div className="research-error" role="alert">
          <span className="research-error-icon" aria-hidden="true">!</span>
          <div><strong>Research interrupted</strong><p>{error}</p></div>
          <button type="button" onClick={() => submit()}>Try again</button>
        </div>
      ) : null}

      {answer ? (
        <div className="research-answer" aria-live="polite">
          <article className="research-answer-summary">
            <p>{answer.answer}</p>
          </article>

          <div className="research-answer-columns">
            <article className="research-proof-card is-evidence">
              <div><span>Evidence</span><small>Server-verified</small></div>
              {answer.document_evidence.map((item) => (
                <section key={item.id} className="is-document-evidence">
                  {item.citation_id ? <span className="research-citation-id">{item.citation_id}</span> : null}
                  <p>{item.claim}</p>
                  {item.document_id && item.page_number ? (
                    <a
                      className="research-source-link"
                      href={`/research/documents/${encodeURIComponent(item.document_id)}/file#page=${item.page_number}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      <cite>{sourceLabel(item)} ↗</cite>
                    </a>
                  ) : item.source_url ? (
                    <a className="research-source-link" href={item.source_url} target="_blank" rel="noreferrer">
                      <cite>{sourceLabel(item)} ↗</cite>
                    </a>
                  ) : <cite>{sourceLabel(item)}</cite>}
                </section>
              ))}
              {answer.data_evidence.map((item) => (
                <section key={item.id}>
                  <p>{item.claim}</p>
                  {item.source_url ? (
                    <a className="research-source-link" href={item.source_url} target="_blank" rel="noreferrer">
                      <cite>{sourceLabel(item)} ↗</cite>
                    </a>
                  ) : <cite>{sourceLabel(item)}</cite>}
                </section>
              ))}
              {answer.document_evidence.length === 0 ? (
                <p className="research-no-docs">No indexed document passage was relevant to this answer.</p>
              ) : null}
            </article>

            <article className="research-proof-card is-inference">
              <div><span>Model inference</span><small>{answer.model.name}</small></div>
              {answer.model_inference.length ? (
                <ul>{answer.model_inference.map((item) => <li key={item}>{item}</li>)}</ul>
              ) : (
                <p>No additional inference was required.</p>
              )}
            </article>
          </div>

          <details className="research-agent-trace">
            <summary>
              <span>Agent trace</span>
              <small>
                {answer.graph?.framework ?? "Workflow"} · {answer.agent_steps.length} tools
                {answer.duration_ms ? ` · ${(answer.duration_ms / 1000).toFixed(1)}s` : ""}
              </small>
            </summary>
            {answer.tool_plan ? <p className="research-plan-reason">{answer.tool_plan.reason}</p> : null}
            <div className="research-trace-meta">
              <span className={`research-citation-status is-${answer.citation_validation?.status ?? "warning"}`}>
                Citations {answer.citation_validation?.status ?? "not checked"}
              </span>
              <small>
                {answer.graph?.version ?? "legacy workflow"}
                {answer.run_id ? ` · ${answer.run_id.slice(0, 8)}` : ""}
              </small>
            </div>
            {answer.graph_trace?.length ? (
              <section className="research-graph-trace" aria-label="LangGraph nodes">
                {answer.graph_trace.map((step, index) => (
                  <article key={`${step.node}-${index}`} className={`is-${step.status}`}>
                    <span>{String(index + 1).padStart(2, "0")}</span>
                    <div><strong>{step.node.replaceAll("_", " ")}</strong><small>{step.detail}</small></div>
                    <b>{step.duration_ms < 1000 ? `${step.duration_ms.toFixed(0)}ms` : `${(step.duration_ms / 1000).toFixed(1)}s`}</b>
                  </article>
                ))}
              </section>
            ) : null}
            <ol className="research-tool-trace">
              {answer.agent_steps.map((step, index) => (
                <li key={`${step.tool}-${index}`}>
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  <strong>{step.tool.replaceAll("_", " ")}</strong>
                  <small>
                    {step.detail}
                    {step.duration_ms !== undefined ? ` · ${step.duration_ms < 1000 ? `${step.duration_ms.toFixed(0)}ms` : `${(step.duration_ms / 1000).toFixed(1)}s`}` : ""}
                  </small>
                </li>
              ))}
            </ol>
          </details>

          <details className="research-limitations">
            <summary>Coverage and limitations</summary>
            <ul>{answer.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
          </details>
        </div>
      ) : null}
    </section>
  );
}
