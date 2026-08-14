import { MetricCard, Panel } from "@/components/cards";
import { Shell } from "@/components/shell";
import { DataTable } from "@/components/table";
import { getModelOverview, getPicks } from "@/lib/api";
import { requireAuth } from "@/lib/auth";
import { formatDate, formatDateTime, formatNumber } from "@/lib/format";
import { getMessages } from "@/lib/i18n";
import { ProfileSelector } from "../models/profile-selector";
import { ProductSubnav } from "@/components/product-subnav";

export const dynamic = "force-dynamic";

function normalizeCode(value: unknown): string {
  const text = String(value ?? "").trim();
  return /^\d+$/.test(text) ? text.padStart(6, "0") : text;
}

export default async function PicksPage({
  searchParams
}: {
  searchParams?: Promise<{ profile?: string }>;
}) {
  const user = await requireAuth();
  const copy = getMessages(user.locale);
  const params = (await searchParams) ?? {};
  const requestedProfile = typeof params.profile === "string" ? params.profile : undefined;
  const [modelOverview, picks] = await Promise.all([
    getModelOverview(requestedProfile),
    getPicks(30, requestedProfile),
  ]);
  const profiles = Array.isArray(modelOverview.model_profiles) ? modelOverview.model_profiles : [];
  const currentProfile = String(picks.profile_name ?? modelOverview.current_profile ?? modelOverview.active_profile ?? "short_5d");
  const activeProfile = String(modelOverview.active_profile ?? "short_5d");
  const pickRows = picks.picks.map((row) => {
    const code = normalizeCode(row.code);
    const name = String(row.name ?? "").trim();
    return {
      ...row,
      code,
      code_detail: name || undefined,
      code_href: code ? `/paper/stocks/${code}` : undefined,
    };
  });

  return (
    <Shell
      title={copy.picks.title}
      subtitle={copy.picks.subtitle}
      locale={user.locale}
      username={user.username}
      role={user.role}
    >
      <ProductSubnav active="signals" items={[
        { key: "signals", label: "Signals", href: "/cn/quant?view=signals" as never },
        { key: "methodology", label: "Methodology", href: "/cn/quant?view=methodology" as never },
        { key: "walk-forward", label: "Walk-forward", href: "/cn/quant?view=walk-forward" as never },
        { key: "explorer", label: "Explorer", href: "/cn/quant?view=explorer" as never }
      ]} />
      <section className="model-view-header">
        <div>
          <p className="model-view-kicker">Viewing picks</p>
          <h2>{currentProfile} <span>{currentProfile === activeProfile ? "Paper active" : "Profile picks"}</span></h2>
        </div>
        <ProfileSelector profiles={profiles} selectedProfile={currentProfile} basePath="/picks" label="Picks model" />
      </section>

      <section className="metrics-grid">
        <MetricCard label={copy.picks.rows} value={formatNumber(picks.rows, user.locale)} hint={copy.picks.rowsHint} />
        <MetricCard label={copy.picks.signalDate} value={formatDate(picks.latest_date, user.locale)} hint={copy.picks.latestSnapshot} />
        <MetricCard
          label={copy.picks.sourceCloseDate}
          value={formatDate(picks.source_close_date, user.locale)}
          hint={`${copy.picks.rawSyncDate}: ${formatDate(picks.raw_sync_date, user.locale)}`}
        />
        <MetricCard label={copy.picks.featureTime} value={formatDateTime(picks.feature_time, user.locale)} />
        <MetricCard label={copy.picks.modelTime} value={formatDateTime(picks.model_time, user.locale)} />
        <MetricCard label={copy.picks.displayedPicks} value={formatNumber(pickRows.length, user.locale)} hint={copy.picks.topRankedRows} />
      </section>

      <Panel title={copy.picks.rankedSignals}>
        <DataTable
          rows={pickRows}
          columns={[
            { key: "rank", label: "Rank" },
            { key: "signal_date", label: copy.picks.signalDate },
            { key: "feature_time", label: copy.picks.featureTime },
            { key: "model_time", label: copy.picks.modelTime },
            { key: "code", label: "Code" },
            { key: "name", label: "Name" },
            { key: "industry", label: "Industry" },
            { key: "score", label: "Model Score" },
            { key: "close", label: "Price At Signal" },
            { key: "bias_20", label: "20D Bias" },
            { key: "pe_ttm", label: "PE TTM" },
            { key: "pb", label: "PB" }
          ]}
          emptyLabel={copy.common.noRows}
          locale={user.locale}
        />
      </Panel>
    </Shell>
  );
}
