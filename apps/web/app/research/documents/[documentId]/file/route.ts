import { NextResponse } from "next/server";

import { RESEARCH_API_BASE_URL } from "@/lib/api";
import { getCurrentUser } from "@/lib/auth";


export async function GET(
  _request: Request,
  context: { params: Promise<{ documentId: string }> }
) {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  const { documentId } = await context.params;
  try {
    const response = await fetch(
      `${RESEARCH_API_BASE_URL}/api/research/documents/${encodeURIComponent(documentId)}/file`,
      { cache: "no-store", signal: AbortSignal.timeout(30_000) }
    );
    if (!response.body) return NextResponse.json({ detail: "Document file unavailable" }, { status: 503 });
    return new Response(response.body, {
      status: response.status,
      headers: {
        "Content-Type": response.headers.get("Content-Type") ?? "application/pdf",
        "Content-Disposition": response.headers.get("Content-Disposition") ?? "inline"
      }
    });
  } catch {
    return NextResponse.json({ detail: "Document file unavailable" }, { status: 503 });
  }
}
