import { NextRequest, NextResponse } from "next/server";

import { API_BASE_URL } from "@/lib/api";
import { getCurrentUser } from "@/lib/auth";


export async function GET() {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  try {
    const response = await fetch(`${API_BASE_URL}/api/research/evaluations`, { cache: "no-store" });
    return NextResponse.json(await response.json(), { status: response.status });
  } catch {
    return NextResponse.json({ detail: "Evaluation service unavailable" }, { status: 503 });
  }
}


export async function POST(_request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  try {
    const response = await fetch(`${API_BASE_URL}/api/research/evaluations/run`, {
      method: "POST",
      headers: { "X-Research-Actor": user.username },
      cache: "no-store",
      signal: AbortSignal.timeout(120_000)
    });
    return NextResponse.json(await response.json(), { status: response.status });
  } catch {
    return NextResponse.json({ detail: "Evaluation run failed" }, { status: 503 });
  }
}
