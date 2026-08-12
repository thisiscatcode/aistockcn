import { NextRequest, NextResponse } from "next/server";

import { RESEARCH_API_BASE_URL } from "@/lib/api";
import { getCurrentUser } from "@/lib/auth";


export async function GET(
  _request: NextRequest,
  context: { params: Promise<{ documentId: string }> }
) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  const { documentId } = await context.params;
  try {
    const response = await fetch(
      `${RESEARCH_API_BASE_URL}/api/research/documents/${encodeURIComponent(documentId)}`,
      { cache: "no-store", signal: AbortSignal.timeout(15_000) }
    );
    const body = await response.json();
    return NextResponse.json(body, { status: response.status });
  } catch {
    return NextResponse.json({ detail: "Document service unavailable" }, { status: 503 });
  }
}
