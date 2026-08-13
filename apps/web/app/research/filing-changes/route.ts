import { NextRequest, NextResponse } from "next/server";

import { RESEARCH_API_BASE_URL } from "@/lib/api";
import { getCurrentUser } from "@/lib/auth";


export async function GET(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  const symbol = request.nextUrl.searchParams.get("symbol") ?? "";
  try {
    const response = await fetch(
      `${RESEARCH_API_BASE_URL}/api/research/filing-changes?symbol=${encodeURIComponent(symbol)}&limit=20`,
      { cache: "no-store", signal: AbortSignal.timeout(15_000) }
    );
    return NextResponse.json(await response.json(), { status: response.status });
  } catch {
    return NextResponse.json({ detail: "Filing change service unavailable" }, { status: 503 });
  }
}


export async function POST(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  try {
    const response = await fetch(`${RESEARCH_API_BASE_URL}/api/research/filing-changes`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Research-Actor": user.username },
      body: await request.text(),
      cache: "no-store",
      signal: AbortSignal.timeout(15_000)
    });
    return NextResponse.json(await response.json(), { status: response.status });
  } catch {
    return NextResponse.json({ detail: "Filing change run could not be queued" }, { status: 503 });
  }
}
