import { NextRequest, NextResponse } from "next/server";

import { API_BASE_URL } from "@/lib/api";
import { appOrigin, getCurrentUser } from "@/lib/auth";

function redirectToAdmin(request: NextRequest, query: string) {
  return NextResponse.redirect(new URL(`/admin${query}`, appOrigin(request)), { status: 303 });
}

export async function POST(request: NextRequest) {
  const user = await getCurrentUser();
  if (!user) {
    return NextResponse.redirect(new URL("/login", appOrigin(request)), { status: 303 });
  }
  if (user.role !== "admin") {
    return redirectToAdmin(request, "?error=forbidden");
  }

  const adminKey = process.env.PANEL_ADMIN_KEY?.trim();
  if (!adminKey) {
    return redirectToAdmin(request, "?error=control_unavailable");
  }

  const formData = await request.formData();
  const excludeSt = formData.get("exclude_st_from_model_candidates") === "on";

  try {
    const response = await fetch(`${API_BASE_URL}/api/control/admin/settings`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-panel-admin-key": adminKey
      },
      body: JSON.stringify({ exclude_st_from_model_candidates: excludeSt }),
      cache: "no-store"
    });

    const payload = (await response.json()) as { code?: string; detail?: { code?: string } };
    if (!response.ok) {
      return redirectToAdmin(request, `?error=${encodeURIComponent(payload.detail?.code ?? payload.code ?? "control_failed")}`);
    }

    return redirectToAdmin(request, `?notice=${encodeURIComponent(payload.code ?? "admin_settings_updated")}`);
  } catch {
    return redirectToAdmin(request, "?error=control_failed");
  }
}
