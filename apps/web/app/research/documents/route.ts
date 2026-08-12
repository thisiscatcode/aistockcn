import { NextRequest, NextResponse } from "next/server";

import { RESEARCH_API_BASE_URL } from "@/lib/api";
import { getCurrentUser } from "@/lib/auth";


export async function GET(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  const symbol = request.nextUrl.searchParams.get("symbol")?.trim() ?? "";
  const query = symbol ? `?symbol=${encodeURIComponent(symbol)}` : "";
  try {
    const response = await fetch(`${RESEARCH_API_BASE_URL}/api/research/documents${query}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(15_000)
    });
    const body = await response.json();
    return NextResponse.json(body, { status: response.status });
  } catch {
    return NextResponse.json({ detail: "Document service unavailable" }, { status: 503 });
  }
}


export async function POST(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  try {
    const formData = await request.formData();
    const response = await fetch(`${RESEARCH_API_BASE_URL}/api/research/documents/upload`, {
      method: "POST",
      headers: { "X-Research-Actor": user.username },
      body: formData,
      cache: "no-store",
      signal: AbortSignal.timeout(120_000)
    });
    const body = await response.json().catch(() => ({ detail: "Invalid document response" }));
    return NextResponse.json(body, { status: response.status });
  } catch {
    return NextResponse.json({ detail: "Document upload failed" }, { status: 503 });
  }
}
