import { NextResponse } from "next/server";

import { US_MARKET_API_BASE_URL } from "@/lib/api";
import { getCurrentUser } from "@/lib/auth";


export async function GET() {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  try {
    const response = await fetch(`${US_MARKET_API_BASE_URL}/api/us/session`, {
      cache: "no-store",
      signal: AbortSignal.timeout(5_000)
    });
    return NextResponse.json(await response.json(), {
      status: response.status,
      headers: { "Cache-Control": "no-store" }
    });
  } catch {
    return NextResponse.json({ detail: "Market session service unavailable" }, { status: 503 });
  }
}
