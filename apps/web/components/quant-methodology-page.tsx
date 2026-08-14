import { Panel } from "@/components/cards";
import { ProductSubnav } from "@/components/product-subnav";
import { Shell } from "@/components/shell";
import { getMarketCapabilities, getUsModelStatus } from "@/lib/api";
import type { PanelUser } from "@/lib/auth";

const tabs = (market: "CN" | "US") => {
  const root = market === "US" ? "/us/quant" : "/cn/quant";
  return [
    { key: "signals", label: "Signals", href: `${root}?view=signals` as never },
    { key: "methodology", label: "Methodology", href: `${root}?view=methodology` as never },
    { key: "walk-forward", label: "Walk-forward", href: `${root}?view=walk-forward` as never },
    { key: "explorer", label: "Explorer", href: `${root}?view=explorer` as never }
  ];
};

export async function QuantMethodologyPage({ market, view, user }: { market: "CN" | "US"; view: "methodology" | "walk-forward"; user: PanelUser }) {
  const [capabilities, usModel] = await Promise.all([
    getMarketCapabilities(market).catch(() => null),
    market === "US" ? getUsModelStatus().catch(() => null) : Promise.resolve(null)
  ]);
  const capability = capabilities?.by_stage.quant;
  return (
    <Shell title="Quant" subtitle="Signals, validation and market data" locale={user.locale} username={user.displayName} role={user.role} market={market}>
      <ProductSubnav items={tabs(market)} active={view} />
      <section className="product-stage-heading">
        <div><span className="stage-icon">⌁</span><div><h1>{view === "methodology" ? "Quantitative Methodology" : "Walk-forward Validation"}</h1><p>{market === "US" ? "US-specific 5-day research pipeline" : "A-share production signal pipeline"}</p></div></div>
        {capability ? <span className={`capability-label status-${capability.status}`}>{capability.status.replaceAll("_", " ")}</span> : null}
      </section>
      {view === "methodology" ? (
        <div className="case-capability-grid quant-method-grid">
          <Panel title="Market isolation"><p className="panel-copy">{market === "US" ? "US calendar, adjusted prices, USD costs and us_5d_v1 artifacts are isolated from A-share production." : "China calendar, price limits, lot size, fees and model artifacts remain market-specific."}</p></Panel>
          <Panel title="Leakage controls"><p className="panel-copy">Features use information available at signal time. Purged expanding windows keep training observations away from validation labels.</p></Panel>
          <Panel title="Activation"><p className="panel-copy">Immutable artifacts, checksum manifests and validation records pass through the PostgreSQL Model Registry before paper permission can change.</p></Panel>
        </div>
      ) : (
        <Panel title="Validation gate" aside={<span className="pill">{usModel?.gate.walk_forward_ready ? "Passed" : market === "US" ? "In validation" : "Registry controlled"}</span>}>
          <div className="summary-list">
            <div><span>Historical coverage</span><strong>{market === "US" ? `${usModel?.gate.available_trading_dates ?? 0} / ${usModel?.gate.required_trading_dates ?? 504} days` : "Market-specific dataset"}</strong></div>
            <div><span>Training artifact</span><strong>{market === "US" ? (usModel?.gate.training_ready ? "Available" : "Gated") : "Registry active model"}</strong></div>
            <div><span>Out-of-sample validation</span><strong>{market === "US" ? (usModel?.gate.walk_forward_ready ? "Passed" : "Pending") : "Recorded per model version"}</strong></div>
            <div><span>Execution permission</span><strong>{market === "US" ? "Disabled" : "Controlled by deployment gate"}</strong></div>
          </div>
        </Panel>
      )}
    </Shell>
  );
}
