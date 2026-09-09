import { NextRequest, NextResponse } from "next/server";

import { API_BASE_URL } from "@/lib/api";
import { appOrigin, getCurrentUser } from "@/lib/auth";

function redirectToModels(request: NextRequest, profile: string, query: string, returnTo: string) {
  const destination = returnTo === "/cn/quant?view=models" ? returnTo : "/models";
  const url = new URL(destination, appOrigin(request));
  const queryParams = new URLSearchParams(query.replace(/^\?/, ""));
  queryParams.forEach((value, key) => url.searchParams.set(key, value));
  url.searchParams.set("profile", profile);
  return NextResponse.redirect(url, { status: 303 });
}

export async function POST(request: NextRequest) {
  const user = await getCurrentUser();
  const formData = await request.formData();
  const profile = String(formData.get("profile") ?? "").trim();
  const returnTo = String(formData.get("return_to") ?? "");
  if (!user) {
    return NextResponse.redirect(new URL("/login", appOrigin(request)), { status: 303 });
  }
  if (user.role !== "admin") {
    return redirectToModels(request, profile, "?error=forbidden", returnTo);
  }
  const adminKey = process.env.PANEL_ADMIN_KEY?.trim();
  if (!adminKey || !profile) {
    return redirectToModels(request, profile, "?error=control_unavailable", returnTo);
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
      return redirectToModels(request, profile, `?error=${encodeURIComponent(payload.detail?.code ?? "activate_failed")}`, returnTo);
    }
    return redirectToModels(request, profile, "?notice=model_activated", returnTo);
  } catch {
    return redirectToModels(request, profile, "?error=activate_failed", returnTo);
  }
}
