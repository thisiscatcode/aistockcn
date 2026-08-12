import { NextRequest, NextResponse } from "next/server";

import { SESSION_COOKIE, appOrigin, authenticateUser, createSessionToken, sessionSecret, useSecureCookies } from "@/lib/auth";

function safeReturnTo(value: FormDataEntryValue | null) {
  const path = String(value ?? "").trim();
  if (!path.startsWith("/") || path.startsWith("//") || path.includes("\\")) {
    return "/overview";
  }
  return path;
}

export async function POST(request: NextRequest) {
  const formData = await request.formData();
  const username = String(formData.get("username") ?? "").trim();
  const password = String(formData.get("password") ?? "");
  const returnTo = safeReturnTo(formData.get("return_to"));
  const origin = appOrigin(request);
  const secureCookies = useSecureCookies(request);
  const user = authenticateUser(username, password);

  if (!user) {
    const invalidUrl = new URL("/login", origin);
    invalidUrl.searchParams.set("error", "invalid");
    invalidUrl.searchParams.set("return_to", returnTo);
    const response = NextResponse.redirect(invalidUrl, { status: 303 });
    response.headers.set("Cache-Control", "no-store");
    return response;
  }

  const response = NextResponse.redirect(new URL(returnTo, origin), { status: 303 });
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
