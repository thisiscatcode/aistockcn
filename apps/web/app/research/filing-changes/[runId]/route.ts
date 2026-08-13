import { NextRequest, NextResponse } from "next/server";

import { RESEARCH_API_BASE_URL } from "@/lib/api";
import { getCurrentUser } from "@/lib/auth";


export async function GET(
  _request: NextRequest,
  context: { params: Promise<{ runId: string }> }
) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  const { runId } = await context.params;
  try {
    const response = await fetch(
      `${RESEARCH_API_BASE_URL}/api/research/filing-changes/${encodeURIComponent(runId)}`,
      { cache: "no-store", signal: AbortSignal.timeout(15_000) }
    );
    return NextResponse.json(await response.json(), { status: response.status });
  } catch {
    return NextResponse.json({ detail: "Filing change result unavailable" }, { status: 503 });
  }
}
