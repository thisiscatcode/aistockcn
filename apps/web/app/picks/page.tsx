import { MetricCard, Panel } from "@/components/cards";
import { Shell } from "@/components/shell";
import { DataTable } from "@/components/table";
import { getModelOverview, getPicks } from "@/lib/api";
import { requireAuth } from "@/lib/auth";
import { formatDate, formatDateTime, formatNumber } from "@/lib/format";
import { getMessages } from "@/lib/i18n";
import { ProfileSelector } from "../models/profile-selector";

export const dynamic = "force-dynamic";

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

  return (
    <Shell
      title={copy.picks.title}
      subtitle={copy.picks.subtitle}
      locale={user.locale}
      username={user.username}
      role={user.role}
    >
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
        <MetricCard label={copy.picks.displayedPicks} value={formatNumber(picks.picks.length, user.locale)} hint={copy.picks.topRankedRows} />
      </section>

      <Panel title={copy.picks.rankedSignals}>
        <DataTable
          rows={picks.picks}
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
