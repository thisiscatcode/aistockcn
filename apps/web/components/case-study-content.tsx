const architectureSteps = [
  { number: "01", title: "Select", detail: "Live US company", tone: "cyan" },
  { number: "02", title: "Ingest", detail: "PDF + page metadata", tone: "blue" },
  { number: "03", title: "Embed", detail: "BGE + pgvector", tone: "violet" },
  { number: "04", title: "Retrieve", detail: "FTS + vector + RRF", tone: "indigo" },
  { number: "05", title: "Rerank", detail: "PyTorch cross-encoder", tone: "magenta" },
  { number: "06", title: "Answer", detail: "Evidence + inference", tone: "green" }
];

const capabilityCards = [
  {
    label: "Grounded research",
    title: "The citation is server data, not model prose",
    body: "Every filing passage retains document ID, filename and page number. The interface renders retrieved evidence separately from model inference and opens the original PDF at the cited page.",
    tags: ["Page citations", "Hybrid RAG", "Evidence boundary"]
  },
  {
    label: "Agent execution",
    title: "Structured plans with allow-listed tools",
    body: "A local LLM creates a JSON plan. FastAPI validates it before executing company lookup, market history, deterministic calculations and document retrieval, with progress streamed over SSE.",
    tags: ["Tool calling", "Structured output", "SSE"]
  },
  {
    label: "Measured quality",
    title: "Retrieval quality is executable",
    body: "The product runs a financial passage-ranking benchmark and persists Top-1 accuracy, mean reciprocal rank, a lexical baseline and per-query ranks for the PyTorch cross-encoder.",
    tags: ["PyTorch", "Evaluation", "Regression signal"]
  }
];

const traceabilityRows = [
  {
    need: "Claims must be traceable to filings",
    response: "Preserve PDF page boundaries and attach citation metadata after retrieval, outside the LLM.",
    evidence: "Clickable filename and page in every answer"
  },
  {
    need: "Research requires more than chat",
    response: "Plan and execute market, calculation, retrieval and comparison tools under a company boundary.",
    evidence: "Streamed agent trace and 2–3 company workflow"
  },
  {
    need: "Semantic search must be testable",
    response: "Fuse PostgreSQL FTS and pgvector candidates, then rerank with a PyTorch cross-encoder.",
    evidence: "Live Top-1, MRR, baseline and case-level ranks"
  },
  {
    need: "Large filings cannot block the API",
    response: "Queue ingestion in PostgreSQL and claim jobs with FOR UPDATE SKIP LOCKED in separate workers.",
    evidence: "Queued, processing, indexed and failed states"
  }
];

const decisions = [
  {
    id: "ADR-01",
    title: "PostgreSQL holds metadata, telemetry and vectors",
    reason: "pgvector keeps filtering, citations, run history and semantic retrieval transactional and inspectable in one production datastore."
  },
  {
    id: "ADR-02",
    title: "Use a two-stage retriever",
    reason: "Fast lexical/vector recall produces candidates; the slower cross-encoder is reserved for the small set where deeper query–passage scoring matters."
  },
  {
    id: "ADR-03",
    title: "Run the LLM locally",
    reason: "Ollama qwen2.5:3b keeps the research service independent of a paid API key while preserving the same structured planning and synthesis contracts."
  },
  {
    id: "ADR-04",
    title: "Isolate research from the customer site",
    reason: "A separate API, worker, frontend image and subdomain let the AI product evolve without rebuilding or replacing the customer-facing deployment."
  }
];

export function CaseStudyContent() {
  return (
    <section className="case-embedded" aria-label="AiStockCN Research Copilot system architecture">
      <section className="case-section" id="architecture">
        <div className="case-section-heading">
          <div>
            <p className="case-kicker">Research architecture</p>
            <h2>From official filing to inspectable answer</h2>
          </div>
          <p>
            The system connects a real US market-data platform to page-aware document retrieval, deterministic
            calculations and a constrained agent. Each result exposes the evidence path used to produce it.
          </p>
        </div>

        <div className="case-flow" role="list" aria-label="Research Copilot workflow">
          {architectureSteps.map((step, index) => (
            <div className={`case-flow-step case-flow-${step.tone}`} role="listitem" key={step.number}>
              <div className="case-flow-top">
                <span>{step.number}</span>
                {index < architectureSteps.length - 1 ? <i aria-hidden="true">→</i> : <i aria-hidden="true">✓</i>}
              </div>
              <strong>{step.title}</strong>
              <small>{step.detail}</small>
            </div>
          ))}
        </div>

        <div className="case-architecture-grid">
          <article className="case-code-card">
            <div className="case-card-bar">
              <span>grounded_answer.json</span>
              <span>validated response contract</span>
            </div>
            <pre><code>{`tool_plan:
  - company_lookup
  - financial_calculator
  - hybrid_document_search
evidence:
  document: JPMorgan-Chase-2024-Annual-Report.pdf
  page: 189
  retrieval: hybrid_rrf_cross_encoder
model_inference:
  separated: true`}</code></pre>
          </article>
          <div className="case-principles">
            <article>
              <span>01 · Grounding</span>
              <h3>Evidence before synthesis</h3>
              <p>The model receives only the company data, calculations and reranked passages selected by tools.</p>
            </article>
            <article>
              <span>02 · Safety</span>
              <h3>Server-controlled tools</h3>
              <p>Unknown planner output is discarded; symbols, file types, sizes and query limits are validated.</p>
            </article>
            <article>
              <span>03 · Operability</span>
              <h3>Observe and recover</h3>
              <p>Retries, rate limits, request IDs, run telemetry and stale-job recovery are part of the runtime.</p>
            </article>
          </div>
        </div>
      </section>

      <section className="case-section" id="delivery">
        <div className="case-section-heading">
          <div>
            <p className="case-kicker">Product · ML · Delivery</p>
            <h2>One workflow, three product guarantees</h2>
          </div>
          <p>Users can run research, inspect the agent path and review retrieval quality from the same product surface.</p>
        </div>
        <div className="case-capability-grid">
          {capabilityCards.map((card, index) => (
            <article className="case-capability-card" key={card.label}>
              <div className="case-capability-index">0{index + 1}</div>
              <p className="case-capability-label">{card.label}</p>
              <h3>{card.title}</h3>
              <p>{card.body}</p>
              <div className="case-tags">{card.tags.map((tag) => <span key={tag}>{tag}</span>)}</div>
            </article>
          ))}
        </div>
      </section>

      <section className="case-section case-trace-section">
        <div className="case-section-heading">
          <div>
            <p className="case-kicker">Requirements traceability</p>
            <h2>Product needs map to verifiable behaviour</h2>
          </div>
          <p>Every important requirement maps to an implementation choice and something visible in the running system.</p>
        </div>
        <div className="case-trace-table" role="table" aria-label="Research requirements traceability">
          <div className="case-trace-row case-trace-header" role="row">
            <span role="columnheader">Product need</span>
            <span role="columnheader">Engineering response</span>
            <span role="columnheader">Product behaviour</span>
          </div>
          {traceabilityRows.map((row) => (
            <div className="case-trace-row" role="row" key={row.need}>
              <strong role="cell">{row.need}</strong>
              <span role="cell">{row.response}</span>
              <span role="cell" className="case-evidence">{row.evidence}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="case-section" id="decisions">
        <div className="case-section-heading">
          <div>
            <p className="case-kicker">Architecture decision record</p>
            <h2>Trade-offs made explicit</h2>
          </div>
          <p>The implementation prioritises traceable research, operational reliability and maintainable system boundaries.</p>
        </div>
        <div className="case-decision-list">
          {decisions.map((decision) => (
            <article key={decision.id}>
              <span>{decision.id}</span>
              <div><h3>{decision.title}</h3><p>{decision.reason}</p></div>
            </article>
          ))}
        </div>
      </section>

      <section className="case-stack-section">
        <div>
          <p className="case-kicker">Implemented end to end</p>
          <h2>AI capability inside a working financial platform.</h2>
        </div>
        <div className="case-stack-list">
          <span>FastAPI</span><span>Next.js</span><span>PostgreSQL</span><span>pgvector</span>
          <span>PyTorch</span><span>Ollama</span><span>Docker</span><span>Kubernetes</span>
          <span>Terraform</span><span>AWS S3</span><span>ECR</span><span>CloudWatch</span>
        </div>
      </section>

      <section className="case-closing">
        <p className="case-kicker">See the evidence path</p>
        <h2>The architecture is documented. The research workflow is live.</h2>
        <p>Sign in, open JPM, ask about operational or cybersecurity risk, and follow the answer into the official annual report page.</p>
      </section>
    </section>
  );
}
