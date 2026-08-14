import DataPage from "../../data/page";
import PicksPage from "../../picks/page";
import { QuantMethodologyPage } from "@/components/quant-methodology-page";
import { requireAuth } from "@/lib/auth";

export const dynamic = "force-dynamic";

type SearchValue = string | string[] | undefined;

export default async function CnQuantPage({
  searchParams
}: {
  searchParams?: Promise<Record<string, SearchValue>>;
}) {
  const params = (await searchParams) ?? {};
  if (params.view === "methodology" || params.view === "walk-forward") {
    const user = await requireAuth();
    return <QuantMethodologyPage market="CN" view={params.view} user={user} />;
  }
  if (params.view === "explorer") {
    return <DataPage searchParams={Promise.resolve(params)} />;
  }
  const profile = typeof params.profile === "string" ? params.profile : undefined;
  return <PicksPage searchParams={Promise.resolve({ profile })} />;
}
