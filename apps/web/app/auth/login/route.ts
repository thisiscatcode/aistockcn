import { NextRequest, NextResponse } from "next/server";

import { SESSION_COOKIE, appOrigin, authenticateUser, createSessionToken, sessionSecret, useSecureCookies } from "@/lib/auth";

export async function POST(request: NextRequest) {
  const formData = await request.formData();
  const username = String(formData.get("username") ?? "").trim();
  const password = String(formData.get("password") ?? "");
  const origin = appOrigin(request);
  const secureCookies = useSecureCookies(request);
  const user = authenticateUser(username, password);

  if (!user) {
    const response = NextResponse.redirect(new URL("/login?error=invalid", origin), { status: 303 });
    response.headers.set("Cache-Control", "no-store");
    return response;
  }

  const response = NextResponse.redirect(new URL("/system-monitor", origin), { status: 303 });
  response.headers.set("Cache-Control", "no-store");
  response.cookies.set(SESSION_COOKIE, createSessionToken(user.username, sessionSecret()), {
    httpOnly: true,
    sameSite: "lax",
    secure: secureCookies,
    path: "/",
    maxAge: 60 * 60 * 12
  });
  return response;
}
