const productSteps = [
  { number: "01", icon: "✦", title: "Research", detail: "Filings, financials and company questions", tone: "cyan" },
  { number: "02", icon: "✓", title: "Verify", detail: "Original documents, pages and calculations", tone: "blue" },
  { number: "03", icon: "⌁", title: "Quantify", detail: "Reproducible signals and walk-forward tests", tone: "violet" },
  { number: "04", icon: "◆", title: "Portfolio", detail: "Holdings, targets and research baskets", tone: "magenta" },
  { number: "05", icon: "⇄", title: "Execute", detail: "Validation-gated, controlled execution", tone: "green" }
];

const principles = [
  { label: "Evidence first", title: "Conclusions you can inspect", body: "Material claims link to document pages, financial periods and deterministic calculations. Model inference is labelled separately." },
  { label: "Test before use", title: "Signals evaluated out of sample", body: "Market-specific features and models pass leakage controls, walk-forward validation and registry gates before activation." },
  { label: "One product", title: "Research connected to decisions", body: "US stocks and CN stocks share one workflow while preserving each market’s sources, calendar, costs and execution rules." }
];

export function CustomerSystemArchitecture() {
  return (
    <main className="case-embedded customer-system-architecture" id="product-flow">
      <section className="case-section">
        <div className="case-section-heading">
          <div><p className="case-kicker">One connected workflow</p><h2>From company evidence to tested decisions</h2></div>
          <p>Research, validation, quantitative analysis, portfolios and execution remain traceable across both supported markets.</p>
        </div>
        <div className="case-flow product-flow" role="list">
          {productSteps.map((step, index) => (
            <div className={`case-flow-step case-flow-${step.tone}`} role="listitem" key={step.number}>
              <div className="case-flow-top"><span>{step.number}</span><i aria-hidden="true">{index < productSteps.length - 1 ? "→" : "✓"}</i></div>
              <strong><b aria-hidden="true">{step.icon}</b>{step.title}</strong><small>{step.detail}</small>
            </div>
          ))}
        </div>
      </section>
      <section className="case-section" id="quantitative-methodology">
        <div className="case-section-heading">
          <div><p className="case-kicker">Product principles</p><h2>Evidence, validation and control by design</h2></div>
          <p>Every layer exposes its source, effective date and readiness state—without turning operational telemetry into customer UI.</p>
        </div>
        <div className="case-capability-grid">
          {principles.map((card, index) => (
            <article className="case-capability-card" key={card.label}>
              <div className="case-capability-index">0{index + 1}</div><p className="case-capability-label">{card.label}</p><h3>{card.title}</h3><p>{card.body}</p>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}
