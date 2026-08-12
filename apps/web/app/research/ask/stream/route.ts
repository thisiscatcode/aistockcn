import { NextRequest, NextResponse } from "next/server";

import { API_BASE_URL } from "@/lib/api";
import { getCurrentUser } from "@/lib/auth";


export async function POST(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  try {
    const body = await request.text();
    const response = await fetch(`${API_BASE_URL}/api/research/ask/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        "X-Research-Actor": user.username
      },
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(180_000)
    });
    if (!response.body) {
      return NextResponse.json({ detail: "Research stream unavailable" }, { status: 503 });
    }
    return new Response(response.body, {
      status: response.status,
      headers: {
        "Content-Type": response.headers.get("Content-Type") ?? "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no"
      }
    });
  } catch {
    return NextResponse.json({ detail: "Research agent unavailable" }, { status: 503 });
  }
}
