import { NextRequest, NextResponse } from "next/server";

import { API_BASE_URL } from "@/lib/api";
import { appOrigin, getCurrentUser } from "@/lib/auth";

function paperRedirect(request: NextRequest, query: string) {
  return NextResponse.redirect(new URL(`/paper${query}`, appOrigin(request)), { status: 303 });
}

export async function POST(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) {
    return NextResponse.redirect(new URL("/login", appOrigin(request)), { status: 303 });
  }
  if (user.role !== "admin") {
    return paperRedirect(request, "?error=forbidden");
  }

  const formData = await request.formData();
  const orderId = String(formData.get("order_id") ?? "").trim();
  if (!orderId) {
    return paperRedirect(request, "?error=missing_order_id");
  }

  const adminKey = process.env.PANEL_ADMIN_KEY?.trim();
  if (!adminKey) {
    return paperRedirect(request, "?error=control_unavailable");
  }

  try {
    const response = await fetch(`${API_BASE_URL}/api/control/paper/orders/${encodeURIComponent(orderId)}/cancel`, {
      method: "POST",
      headers: {
        "x-panel-admin-key": adminKey
      },
      cache: "no-store"
    });
    const payload = (await response.json()) as { code?: string; detail?: { code?: string } };
    if (!response.ok) {
      const code = payload.detail?.code ?? payload.code ?? "cancel_failed";
      return paperRedirect(request, `?error=${encodeURIComponent(code)}`);
    }
    return paperRedirect(request, `?notice=${encodeURIComponent(payload.code ?? "cancelled_order")}`);
  } catch {
    return paperRedirect(request, "?error=cancel_failed");
  }
}
