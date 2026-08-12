const architectureSteps = [
  { number: "01", title: "Ingest", detail: "BaoStock + AKShare", tone: "cyan" },
  { number: "02", title: "Normalise", detail: "Parquet + PyArrow", tone: "blue" },
  { number: "03", title: "Engineer", detail: "Training + inference", tone: "violet" },
  { number: "04", title: "Model", detail: "LightGBM profiles", tone: "indigo" },
  { number: "05", title: "Validate", detail: "Walk-forward tests", tone: "magenta" },
  { number: "06", title: "Operate", detail: "Signals + paper trades", tone: "green" }
];

const capabilityCards = [
  {
    label: "Data foundation",
    title: "Traceable market-data pipeline",
    body: "The stock universe, daily prices, valuation data and reference datasets move through explicit, inspectable artifacts with freshness and coverage checks.",
    tags: ["Data lineage", "Parquet", "Quality gates"]
  },
  {
    label: "Quant research",
    title: "Models tested out of sample",
    body: "Training and inference remain separate. Model profiles are evaluated with expanding-window walk-forward tests before their scores enter the operating workflow.",
    tags: ["LightGBM", "No leakage", "Walk-forward"]
  },
  {
    label: "Operations",
    title: "Signals connected to execution",
    body: "Ranked targets, portfolio state, orders and fills stay reviewable while batch progress, failure reasons and recovery state remain visible to operators.",
    tags: ["Signal ranking", "Paper trading", "Telemetry"]
  }
];

export function CustomerSystemArchitecture() {
  return (
    <section className="case-embedded customer-system-architecture" aria-label="AiStockCN system architecture">
      <section className="case-section" id="system-architecture">
        <div className="case-section-heading">
          <div>
            <p className="case-kicker">System architecture</p>
            <h2>One continuous path from market data to execution</h2>
          </div>
          <p>
            AiStockCN connects data ingestion, feature engineering, model validation, signal generation and
            paper execution through explicit artifacts and observable operating states.
          </p>
        </div>

        <div className="case-flow" role="list" aria-label="AiStockCN data and model workflow">
          {architectureSteps.map((step, index) => (
            <div className={`case-flow-step case-flow-${step.tone}`} role="listitem" key={step.number}>
              <div className="case-flow-top">
                <span>{step.number}</span>
                <i aria-hidden="true">{index < architectureSteps.length - 1 ? "→" : "✓"}</i>
              </div>
              <strong>{step.title}</strong>
              <small>{step.detail}</small>
            </div>
          ))}
        </div>
      </section>

      <section className="case-section" id="platform-capabilities">
        <div className="case-section-heading">
          <div>
            <p className="case-kicker">Platform capabilities</p>
            <h2>Research quality and operations in the same system</h2>
          </div>
          <p>
            Each layer exposes its inputs, outputs and current state, so research results can be traced and
            operating decisions can be reviewed without relying on hidden process state.
          </p>
        </div>

        <div className="case-capability-grid">
          {capabilityCards.map((card, index) => (
            <article className="case-capability-card" key={card.label}>
              <div className="case-capability-index">0{index + 1}</div>
              <p className="case-capability-label">{card.label}</p>
              <h3>{card.title}</h3>
              <p>{card.body}</p>
              <div className="case-tags">
                {card.tags.map((tag) => <span key={tag}>{tag}</span>)}
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="case-stack-section">
        <div>
          <p className="case-kicker">Integrated platform</p>
          <h2>Financial data, quantitative models and live operations.</h2>
        </div>
        <div className="case-stack-list" aria-label="AiStockCN technology stack">
          <span>Python</span><span>FastAPI</span><span>Pandas</span><span>PyArrow</span>
          <span>LightGBM</span><span>scikit-learn</span><span>PostgreSQL</span><span>Next.js</span>
          <span>React</span><span>Docker Compose</span><span>REST APIs</span><span>Futu Gateway</span>
        </div>
      </section>
    </section>
  );
}
