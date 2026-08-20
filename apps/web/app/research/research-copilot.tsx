"use client";

import { FormEvent, useState } from "react";

import type { ResearchAnswer } from "@/lib/api";
import {
  buildResearchAnswerView,
  documentEvidenceHref,
  presentationSourceHref,
} from "./research-answer-view";


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

function auditValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

function revealAnswerSection(id: string) {
  const element = document.getElementById(id);
  if (!element) return;
  if (element instanceof HTMLDetailsElement) element.open = true;
  element.scrollIntoView({ behavior: "smooth", block: "start" });
}

export function ResearchAnswerResult({ answer }: { answer: ResearchAnswer }) {
  const presentation = answer.presentation;
  const view = buildResearchAnswerView(answer);
  const { takeaway, interpretations, sources, metrics } = view;

  return (
    <div className="research-answer" aria-live="polite">
      <article className="research-takeaway-card">
        <div className="research-result-label">
          <span aria-hidden="true">✦</span>
          <strong>Key takeaway</strong>
          {presentation?.source_verified ? <small>✓ Grounded in SEC evidence</small> : null}
        </div>
        <p>{takeaway}</p>
        <div className="research-takeaway-footer">
          {presentation?.period.end_date ? (
            <span className="research-period-label">
              FY{presentation.period.fiscal_year ?? ""} · period ended {presentation.period.end_date}
            </span>
          ) : <span />}
          <div>
            {view.showInterpretation ? (
              <button type="button" onClick={() => revealAnswerSection("research-interpretation")}>Why this matters</button>
            ) : null}
            <button type="button" onClick={() => revealAnswerSection("research-evidence")}>View evidence</button>
          </div>
        </div>
      </article>

      {metrics.length ? (
        <section className="research-metric-comparison" aria-labelledby="research-metric-title">
          <div className="research-result-section-title">
            <div><span aria-hidden="true">↗</span><h3 id="research-metric-title">Financial trend</h3></div>
            <small>Latest comparable annual period</small>
          </div>
          <div className="research-metric-table" role="table" aria-label="Financial metric comparison">
            <div className="research-metric-row is-heading" role="row">
              <span role="columnheader">Metric</span>
              <span role="columnheader">Latest period</span>
              <span role="columnheader">Change</span>
            </div>
            {metrics.map((metric) => (
              <div className="research-metric-row" role="row" key={metric.key}>
                <strong role="cell">{metric.label}</strong>
                <span role="cell" className="research-metric-value">{metric.formatted_value}</span>
                <span role="cell" className={`research-metric-change is-${metric.direction}`}>
                  {metric.formatted_change}
                </span>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {view.showInterpretation ? (
        <section id="research-interpretation" className="research-interpretation" aria-labelledby="research-interpretation-title">
          <div className="research-result-section-title">
            <div><span aria-hidden="true">◎</span><h3 id="research-interpretation-title">What it means</h3></div>
          </div>
          <ul>
            {interpretations.slice(0, 3).map((item, index) => (
              <li key={`${item.kind}-${index}`}>
                <span className={`research-interpretation-kind is-${item.kind}`}>
                  {item.kind === "model_inference" ? "Interpretation" : "Calculated fact"}
                </span>
                <p>{item.text}</p>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="research-sources" aria-labelledby="research-sources-title">
        <div className="research-result-section-title">
          <div><span aria-hidden="true">⌁</span><h3 id="research-sources-title">Sources</h3></div>
          {answer.citation_validation ? (
            <small className={`research-source-validation is-${answer.citation_validation.status}`}>
              {answer.citation_validation.status === "passed" ? "Citations verified" : `Citations ${answer.citation_validation.status}`}
            </small>
          ) : null}
        </div>
        <div className="research-source-chips">
          {sources.map((source) => {
            const href = presentationSourceHref(source);
            const content = <><span>{source.label}</span>{source.period_end ? <small>Ended {source.period_end}</small> : null}</>;
            return href ? (
              <a href={href} target="_blank" rel="noreferrer" key={source.id}>{content}<b aria-hidden="true">↗</b></a>
            ) : <span className="research-source-chip" key={source.id}>{content}</span>;
          })}
          {presentation?.source_verified ? <span className="research-source-chip is-verified">✓ Source verified</span> : null}
        </div>

        <details id="research-evidence" className="research-evidence-disclosure">
          <summary>View evidence</summary>
          {metrics.length ? (
            <div className="research-metric-evidence-list">
              {metrics.map((metric) => (
                <article key={metric.key}>
                  <header><strong>{metric.label}</strong><span>{metric.formatted_value} · {metric.formatted_change}</span></header>
                  {metric.calculation ? <p>Calculation: {metric.calculation}</p> : null}
                  {metric.sources.map((source, index) => (
                    <dl key={`${metric.key}-${source.evidence_id ?? index}`}>
                      <div><dt>SEC concept</dt><dd>{auditValue(source.taxonomy)}:{auditValue(source.concept)}</dd></div>
                      <div><dt>Form / filed</dt><dd>{auditValue(source.form)} · {auditValue(source.filed_date)}</dd></div>
                      <div><dt>Accession</dt><dd>{auditValue(source.accession_number)}</dd></div>
                      <div><dt>Raw value</dt><dd>{auditValue(source.raw_value)} {auditValue(source.raw_unit)}</dd></div>
                      <div><dt>Evidence ID</dt><dd>{auditValue(source.evidence_id)}</dd></div>
                      <div className="is-wide"><dt>Locator</dt><dd>{auditValue(source.locator)}</dd></div>
                    </dl>
                  ))}
                </article>
              ))}
            </div>
          ) : null}
          {answer.document_evidence.length ? (
            <div className="research-document-evidence-list">
              {answer.document_evidence.map((item) => {
                const href = documentEvidenceHref(item);
                return (
                  <article key={item.id}>
                    <span className="research-citation-id">{item.citation_id ?? "SEC"}</span>
                    <p>{item.claim}</p>
                    {href ? <a href={href} target="_blank" rel="noreferrer">{sourceLabel(item)} ↗</a> : <cite>{sourceLabel(item)}</cite>}
                  </article>
                );
              })}
            </div>
          ) : null}
        </details>
      </section>

      <details className="research-audit-details">
        <summary>
          <span>Advanced details</span>
          <small>Model, tools, latency and raw evidence</small>
        </summary>
        <div className="research-audit-grid">
          <div><span>Model</span><strong>{answer.model.provider} · {answer.model.name}</strong></div>
          <div><span>Workflow</span><strong>{answer.graph?.framework ?? "Research workflow"} · {answer.graph?.version ?? "legacy"}</strong></div>
          <div><span>Latency</span><strong>{answer.duration_ms ? `${(answer.duration_ms / 1000).toFixed(1)}s` : "—"}</strong></div>
          <div><span>Run ID</span><strong>{answer.run_id ?? "—"}</strong></div>
          <div><span>Fallback</span><strong>{presentation?.fallback_state ?? "None"}</strong></div>
          <div><span>Citation validation</span><strong>{answer.citation_validation?.status ?? "Not checked"}</strong></div>
        </div>
        {answer.tool_plan ? (
          <section className="research-audit-plan">
            <h4>Tool plan</h4>
            <p>{answer.tool_plan.reason}</p>
            <div>{answer.tool_plan.tools.map((tool) => <span key={tool}>{tool.replaceAll("_", " ")}</span>)}</div>
          </section>
        ) : null}
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
              <small>{step.detail}{step.duration_ms !== undefined ? ` · ${step.duration_ms < 1000 ? `${step.duration_ms.toFixed(0)}ms` : `${(step.duration_ms / 1000).toFixed(1)}s`}` : ""}</small>
            </li>
          ))}
        </ol>
        <details className="research-raw-evidence">
          <summary>Raw evidence payload</summary>
          {[...answer.data_evidence, ...answer.document_evidence].map((item) => (
            <article key={`raw-${item.id}`}>
              <strong>{item.id}</strong><p>{item.claim}</p><code>{item.source} · {item.locator}</code>
            </article>
          ))}
        </details>
      </details>

      {answer.limitations.length ? (
        <details className="research-limitations">
          <summary>Coverage and limitations</summary>
          <ul>{answer.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
        </details>
      ) : null}
    </div>
  );
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
      <div className="research-suggestions" aria-label="Suggested questions">
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
          rows={1}
        />
        <button type="submit" disabled={loading || !question.trim()}>
          <span aria-hidden="true">✦</span> {loading ? "Researching…" : "Ask"}
        </button>
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

      {answer ? <ResearchAnswerResult answer={answer} /> : null}
    </section>
  );
}
