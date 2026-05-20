import { NextRequest, NextResponse } from "next/server";

import { API_BASE_URL } from "@/lib/api";
import { appOrigin, getCurrentUser } from "@/lib/auth";

function redirectToModels(request: NextRequest, profile: string, query: string) {
  const suffix = `${query}${query.includes("?") ? "&" : "?"}profile=${encodeURIComponent(profile)}`;
  return NextResponse.redirect(new URL(`/models${suffix}`, appOrigin(request)), { status: 303 });
}

export async function POST(request: NextRequest) {
  const user = await getCurrentUser();
  const formData = await request.formData();
  const profile = String(formData.get("profile") ?? "").trim();
  if (!user) {
    return NextResponse.redirect(new URL("/login", appOrigin(request)), { status: 303 });
  }
  if (user.role !== "admin") {
    return redirectToModels(request, profile, "?error=forbidden");
  }
  const adminKey = process.env.PANEL_ADMIN_KEY?.trim();
  if (!adminKey || !profile) {
    return redirectToModels(request, profile, "?error=control_unavailable");
  }

  try {
    const response = await fetch(`${API_BASE_URL}/api/control/model/activate?profile=${encodeURIComponent(profile)}`, {
      method: "POST",
      headers: {
        "x-panel-admin-key": adminKey
      },
      cache: "no-store"
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({})) as { detail?: { code?: string } };
      return redirectToModels(request, profile, `?error=${encodeURIComponent(payload.detail?.code ?? "activate_failed")}`);
    }
    return redirectToModels(request, profile, "?notice=model_activated");
  } catch {
    return redirectToModels(request, profile, "?error=activate_failed");
  }
}
