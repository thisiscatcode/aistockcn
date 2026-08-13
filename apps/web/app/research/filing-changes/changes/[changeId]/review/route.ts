import { NextRequest, NextResponse } from "next/server";

import { RESEARCH_API_BASE_URL } from "@/lib/api";
import { getCurrentUser } from "@/lib/auth";


export async function POST(
  request: NextRequest,
  context: { params: Promise<{ changeId: string }> }
) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  const { changeId } = await context.params;
  try {
    const response = await fetch(
      `${RESEARCH_API_BASE_URL}/api/research/filing-changes/changes/${encodeURIComponent(changeId)}/review`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Research-Actor": user.username },
        body: await request.text(),
        cache: "no-store",
        signal: AbortSignal.timeout(15_000)
      }
    );
    return NextResponse.json(await response.json(), { status: response.status });
  } catch {
    return NextResponse.json({ detail: "Review could not be saved" }, { status: 503 });
  }
}
