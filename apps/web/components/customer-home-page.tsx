import Link from "next/link";
import { redirect } from "next/navigation";

import { CustomerSystemArchitecture } from "@/components/customer-system-architecture";
import { BrandLockup } from "@/components/brand-mark";
import { getCurrentUser } from "@/lib/auth";

export async function CustomerHomePage() {
  const user = await getCurrentUser();
  if (user) redirect("/us/overview");

  return (
    <div className="page-dark customer-home-page">
      <div className="shell shell-dark customer-home-shell">
        <header className="hero-landing customer-home-hero unified-home-hero">
          <nav className="landing-nav" aria-label="Public navigation">
            <Link href="/" className="landing-brand landing-brand-lockup" aria-label="AiStockCN home">
              <BrandLockup />
            </Link>
            <div className="landing-auth-actions">
              <a href="#product-flow">Product</a>
              <a href="#quantitative-methodology">Methodology</a>
              <Link href="/login" className="landing-login">Sign in</Link>
              <Link href="/login" className="landing-login landing-guest-login">Guest sign in</Link>
            </div>
          </nav>
          <section className="hero-landing-stage">
            <div className="unified-hero-grid">
              <div className="hero-panel-copy-wrap">
                <p className="eyebrow hero-dark-eyebrow">US STOCKS + CN STOCKS</p>
                <div className="unified-hero-title-stack">
                  <h1>Research with AI.</h1>
                  <p className="unified-hero-thesis">Verify every conclusion.</p>
                  <p className="unified-hero-outcome">From evidence to tested strategies.</p>
                </div>
                <p className="hero-panel-copy hero-panel-copy-lead">
                  Analyse 10,000+ US and China stocks through filings, financials, source-linked answers,
                  reproducible signals and controlled execution.
                </p>
                <div className="landing-actions">
                  <Link href="/login?return_to=%2Fus%2Fresearch%3Fsymbol%3DAAPL" className="landing-primary-cta">Research AAPL <span>→</span></Link>
                  <a href="#quantitative-methodology" className="landing-secondary-cta">View quantitative methodology</a>
                </div>
              </div>
              <div className="landing-evidence-card" aria-label="Research answer preview">
                <div className="landing-evidence-top"><span>✦ AI RESEARCH</span><strong>AAPL</strong></div>
                <h2>What changed in revenue, margins and risk language?</h2>
                <div className="landing-evidence-row"><span className="evidence-check">✓</span><p><strong>Document evidence</strong><small>10-K · page 29 · source linked</small></p></div>
                <div className="landing-evidence-row"><span className="evidence-check">✓</span><p><strong>Financial evidence</strong><small>FY2025 revenue · period and unit verified</small></p></div>
                <div className="landing-evidence-row inference"><span>◇</span><p><strong>Model inference</strong><small>Clearly separated from source facts</small></p></div>
              </div>
            </div>
          </section>
        </header>
        <CustomerSystemArchitecture />
      </div>
    </div>
  );
}
