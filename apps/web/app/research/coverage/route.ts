import { NextRequest, NextResponse } from "next/server";

import { RESEARCH_API_BASE_URL } from "@/lib/api";
import { getCurrentUser } from "@/lib/auth";


export async function GET(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  const limit = request.nextUrl.searchParams.get("limit") ?? "100";
  try {
    const response = await fetch(
      `${RESEARCH_API_BASE_URL}/api/research/coverage?limit=${encodeURIComponent(limit)}`,
      { cache: "no-store", signal: AbortSignal.timeout(15_000) }
    );
    return NextResponse.json(await response.json(), { status: response.status });
  } catch {
    return NextResponse.json({ detail: "Coverage service unavailable" }, { status: 503 });
  }
}
