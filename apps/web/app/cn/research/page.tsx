import Link from "next/link";

import { MetricCard, Panel } from "@/components/cards";
import { Shell } from "@/components/shell";
import { DataTable } from "@/components/table";
import { getResearchCompanies, getResearchCompany, getResearchDocuments } from "@/lib/api";
import { requireAuth } from "@/lib/auth";
import { formatNumber } from "@/lib/format";
import { CnDisclosureSync } from "./cn-disclosure-sync";

export const dynamic = "force-dynamic";

export default async function CnResearchPage({
  searchParams
}: {
  searchParams?: Promise<{ q?: string; symbol?: string }>;
}) {
  const user = await requireAuth();
  const params = (await searchParams) ?? {};
  const query = String(params.q ?? "").trim();
  const symbol = String(params.symbol ?? "").trim();
  const [result, snapshot, documentResult] = await Promise.all([
    getResearchCompanies(query, 30, "CN").catch(() => ({ query, rows: 0, total_active: 0, companies: [] })),
    symbol ? getResearchCompany(symbol, 30, "CN").catch(() => null) : Promise.resolve(null),
    symbol ? getResearchDocuments(symbol, "CN").catch(() => ({ rows: 0, documents: [] })) : Promise.resolve({ rows: 0, documents: [] })
  ]);
  const matches = result.companies;

  return (
    <Shell title="CN Stock Research" subtitle="Official disclosures and financial evidence" locale={user.locale} username={user.displayName} role={user.role} market="CN">
      <section className="product-stage-heading">
        <div><span className="stage-icon">✦</span><div><h1>Company Research</h1><p>Find a CN stock and review traceable market and disclosure evidence.</p></div></div>
        <span className="capability-label status-in_validation">In validation</span>
      </section>
      <form className="us-stock-search product-search" action="/cn/research" method="get">
        <input name="q" defaultValue={query} placeholder="Search ticker or company name" aria-label="Search CN stocks" autoFocus />
        <button type="submit">Search</button>
        {query ? <Link href="/cn/research">Clear</Link> : null}
      </form>
      {snapshot?.company ? (
        <Panel title={`${snapshot.company.symbol} · ${snapshot.company.stock_name_zh || snapshot.company.stock_name || "Company"}`} aside={<span className="pill">Official evidence</span>}>
          <div className="cn-research-company-bar"><div><span>Exchange</span><strong>{snapshot.company.market || "—"}</strong></div><div><span>Currency</span><strong>{snapshot.company.currency || "CNY"}</strong></div><div><span>Indexed filings</span><strong>{documentResult.documents.filter((item) => item.status === "indexed").length}</strong></div></div>
          <CnDisclosureSync symbol={snapshot.company.symbol} />
          <div className="cn-document-list">
            {documentResult.documents.map((document) => <a key={document.id} href={`/research/documents/${encodeURIComponent(document.id)}/file`} target="_blank" rel="noreferrer"><strong>{document.filename}</strong><span>{document.filing_date || "—"} · {document.status.replaceAll("_", " ")}</span></a>)}
            {documentResult.documents.length === 0 ? <p className="panel-copy">No filing has been selected for this company yet.</p> : null}
          </div>
        </Panel>
      ) : null}
      <section className="metrics-grid compact-metrics">
        <MetricCard label="Search Results" value={formatNumber(matches.length, user.locale)} />
        <MetricCard label="Evidence Policy" value="Official first" hint="Exchange disclosures before third-party data" />
        <MetricCard label="Language" value="中文 / English" />
      </section>
      <Panel title={query ? `Results for “${query}”` : "CN stock companies"}>
        <DataTable
          rows={matches.map((stock) => ({ code: stock.symbol, code_href: `/cn/research?symbol=${encodeURIComponent(stock.symbol)}`, company: stock.stock_name_zh || stock.stock_name, exchange: stock.market }))}
          columns={[{ key: "code", label: "Ticker" }, { key: "company", label: "Company" }, { key: "exchange", label: "Exchange" }]}
          locale={user.locale}
          emptyLabel="No matching company found."
          pageSize={25}
        />
      </Panel>
    </Shell>
  );
}
