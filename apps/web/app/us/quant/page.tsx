import UsDataPage from "../data/page";
import UsPicksPage from "../picks/page";
import { QuantMethodologyPage } from "@/components/quant-methodology-page";
import { requireAuth } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function UsQuantPage({
  searchParams
}: {
  searchParams?: Promise<{ view?: string; type?: string; search?: string }>;
}) {
  const params = (await searchParams) ?? {};
  if (params.view === "methodology" || params.view === "walk-forward") {
    const user = await requireAuth();
    return <QuantMethodologyPage market="US" view={params.view} user={user} />;
  }
  if (params.view === "explorer") {
    return <UsDataPage searchParams={Promise.resolve({ search: params.search })} />;
  }
  return <UsPicksPage searchParams={Promise.resolve({ type: params.type })} />;
}
