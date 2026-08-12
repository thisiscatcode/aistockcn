import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { CaseStudyContent } from "@/components/case-study-content";
import { CustomerHomePage } from "@/components/customer-home-page";
import { getResearchCompanies, getResearchDocuments } from "@/lib/api";
import { getCurrentUser } from "@/lib/auth";
import { formatNumber } from "@/lib/format";

export const dynamic = "force-dynamic";

const isResearchSurface = (process.env.PANEL_PUBLIC_HOSTS ?? "")
  .split(",")
  .some((host) => host.trim().toLowerCase().startsWith("research."));

export function generateMetadata(): Metadata {
  if (!isResearchSurface) {
    return {
      title: "AiStockCN — Systematic Equity Research Platform",
      description: "Live market data, quantitative research, model signals and paper-trading operations."
    };
  }
  return {
    title: "AiStockCN Research Copilot — Evidence-grounded equity research",
    description: "Research US public companies with live market data, deterministic calculations and clearly separated evidence and inference."
  };
}

export default async function HomePage() {
  if (!isResearchSurface) {
    return <CustomerHomePage />;
  }

  const user = await getCurrentUser();
  if (user) {
    redirect("/overview");
  }

  const [usCompanies, jpmDocuments] = await Promise.all([
    getResearchCompanies("", 6).catch(() => ({ query: "", rows: 0, total_active: 0, companies: [] })),
    getResearchDocuments("JPM").catch(() => ({ rows: 0, documents: [] }))
  ]);
  const officialPages = jpmDocuments.documents
    .filter((document) => document.status === "indexed")
    .reduce((total, document) => total + Number(document.page_count ?? 0), 0);
  return (
    <div className="page-dark research-home-page">
      <div className="shell shell-dark">
        <header className="hero-landing">
          <section className="hero-landing-stage">
            <div className="hero-landing-grid">
              <div className="hero-panel-copy-wrap">
                <p className="eyebrow hero-dark-eyebrow">AI-POWERED FINANCIAL RESEARCH</p>
                <p className="hero-platform-title">AiStockCN Research Copilot</p>
                <h1 className="text-gradient-accent research-home-title">Research companies with evidence, not guesses.</h1>
                <p className="hero-panel-copy hero-panel-copy-lead">
                  Ask a US-company question and trace the answer back to live market observations and
                  deterministic calculations, official annual reports and page-level source citations.
                </p>
                <form action="/research" method="get" className="research-home-search">
                  <label htmlFor="home-research-company">Start with a US company</label>
                  <div>
                    <input id="home-research-company" name="q" type="search" placeholder="NVDA, Microsoft, JPMorgan…" />
                    <button type="submit">Open Research Copilot <span aria-hidden="true">→</span></button>
                  </div>
                </form>
                <div className="research-home-capabilities" aria-label="Research Copilot capabilities">
                  <span>Live market evidence</span>
                  <span>Clickable PDF citations</span>
                  <span>Evidence vs inference</span>
                </div>
              </div>

              <div className="hero-visual-stack">
                <div className="hero-panel-header hero-glass-card hero-snapshot-heading">
                  <div>
                    <p className="hero-panel-kicker">Connected financial platform</p>
                    <h2>Live Research Surface</h2>
                  </div>
                  <Link
                    href="/login?return_to=/overview"
                    className="nav-link hero-login-button"
                    aria-label="Login to open AiStockCN Research Copilot"
                  >
                    <span className="hero-login-copy">
                      <span className="hero-login-meta">Existing user</span>
                      <span className="hero-login-label">Open Copilot</span>
                    </span>
                    <span className="hero-login-arrow" aria-hidden="true">
                      &rarr;
                    </span>
                  </Link>
                </div>

                <div>
                  <div className="hero-panel-grid">
                    <div className="hero-panel-metric hero-live-card hero-glass-card hero-blue-top-card">
                      <span>Research system</span>
                      <strong className="metric-live-value">
                        <span className="metric-live-dot" aria-hidden="true" />
                        Live
                      </strong>
                    </div>
                    <div className="hero-panel-metric hero-glass-card hero-blue-top-card">
                      <span>US equity universe</span>
                      <strong>{formatNumber(usCompanies.total_active, "en")}</strong>
                    </div>
                    <div className="hero-panel-metric hero-glass-card hero-blue-top-card">
                      <span>Official filing pages</span>
                      <strong>{officialPages || "—"}</strong>
                    </div>
                  </div>
                  <div className="research-home-company-strip" aria-label="Example live US companies">
                    {usCompanies.companies.slice(0, 4).map((company) => (
                      <span key={company.symbol}>
                        <strong>{company.symbol}</strong>
                        <small>{company.stock_name || company.market || "US equity"}</small>
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </section>
        </header>

        <div id="research-proof">
          <CaseStudyContent />
        </div>
      </div>
    </div>
  );
}
