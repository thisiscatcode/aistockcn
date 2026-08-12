import { NextRequest, NextResponse } from "next/server";

import { getCurrentUser } from "@/lib/auth";
import { API_BASE_URL } from "@/lib/api";


export async function POST(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }

  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ detail: "Invalid JSON body" }, { status: 400 });
  }

  try {
    const response = await fetch(`${API_BASE_URL}/api/research/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Research-Actor": user.username },
      body: JSON.stringify(payload),
      cache: "no-store",
      signal: AbortSignal.timeout(130_000)
    });
    const body = await response.json().catch(() => ({ detail: "Research service returned an invalid response" }));
    return NextResponse.json(body, { status: response.status });
  } catch {
    return NextResponse.json(
      { detail: "Research synthesis is temporarily unavailable" },
      { status: 503 }
    );
  }
}
