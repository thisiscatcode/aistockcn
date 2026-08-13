import { Panel } from "@/components/cards";
import { DataTable } from "@/components/table";
import { getUsPicks } from "@/lib/api";
import { requireAuth } from "@/lib/auth";
import { formatDate } from "@/lib/format";
import { UsShell } from "../us-components";

export const dynamic = "force-dynamic";

export default async function UsPicksPage({
  searchParams
}: {
  searchParams?: Promise<{ type?: string }>;
}) {
  const user = await requireAuth();
  const type = (await searchParams)?.type === "lobster" ? "lobster" : "cat";
  const response = await getUsPicks(50, type);
  const rows = response.picks.map((pick) => ({
    rank: pick.rank,
    symbol: pick.symbol,
    symbol_href: `/research?symbol=${encodeURIComponent(pick.symbol)}`,
    company: pick.name,
    exchange: pick.exchange,
    industry: pick.industry,
    score: pick.score,
    signal_date: pick.signal_date
  }));

  return (
    <UsShell user={user} title="US Picks" subtitle="Rules-based selection snapshots">
      <div className="us-selection-tabs" aria-label="US selection type">
        <a className={type === "cat" ? "is-active" : ""} href="/us/picks?type=cat">Cat selection</a>
        <a className={type === "lobster" ? "is-active" : ""} href="/us/picks?type=lobster">Lobster selection</a>
      </div>
      <div className="us-evidence-note">
        <strong>Rules-based selection</strong>
        <span>ML picks appear after walk-forward validation.</span>
      </div>
      <Panel title={`${type === "cat" ? "Cat" : "Lobster"} Selection`} aside={<span className="pill">{formatDate(response.data_freshness?.selection, user.locale)}</span>}>
        <DataTable
          rows={rows}
          columns={[
            { key: "rank", label: "Rank" },
            { key: "symbol", label: "Symbol" },
            { key: "company", label: "Company" },
            { key: "exchange", label: "Exchange" },
            { key: "industry", label: "Industry" },
            { key: "score", label: "Score" },
            { key: "signal_date", label: "Signal Date" }
          ]}
          locale={user.locale}
          pageSize={25}
          emptyLabel="No US selection snapshot is available for this list."
        />
      </Panel>
    </UsShell>
  );
}
