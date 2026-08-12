import { NextRequest, NextResponse } from "next/server";

import { API_BASE_URL } from "@/lib/api";
import { getCurrentUser } from "@/lib/auth";


export async function POST(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  try {
    const body = await request.text();
    const response = await fetch(`${API_BASE_URL}/api/research/compare`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Research-Actor": user.username },
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(180_000)
    });
    const payload = await response.json().catch(() => ({ detail: "Invalid comparison response" }));
    return NextResponse.json(payload, { status: response.status });
  } catch {
    return NextResponse.json({ detail: "Comparison agent unavailable" }, { status: 503 });
  }
}
