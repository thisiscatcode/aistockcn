import { NextResponse } from "next/server";

import { getCurrentUser } from "@/lib/auth";
import { getCnMarketSession } from "@/lib/cn-market-session";

export async function GET() {
  const user = await getCurrentUser();
  if (!user) return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  return NextResponse.json(getCnMarketSession(), {
    headers: { "Cache-Control": "no-store" }
  });
}
