import { NextRequest, NextResponse } from "next/server";

import { RESEARCH_API_BASE_URL } from "@/lib/api";
import { getCurrentUser } from "@/lib/auth";

export async function POST(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  try {
    const payload = await request.json();
    const response = await fetch(`${RESEARCH_API_BASE_URL}/api/research/documents/cn/sync`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Research-Actor": user.username },
      body: JSON.stringify({ ...payload, market: "CN" }),
      cache: "no-store",
      signal: AbortSignal.timeout(180_000)
    });
    const body = await response.json().catch(() => ({ detail: "Invalid disclosure sync response" }));
    return NextResponse.json(body, { status: response.status });
  } catch {
    return NextResponse.json({ detail: "Official disclosure sync unavailable" }, { status: 503 });
  }
}
