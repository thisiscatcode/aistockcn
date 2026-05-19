import { NextRequest, NextResponse } from "next/server";

import { SESSION_COOKIE, appOrigin, useSecureCookies } from "@/lib/auth";

export async function POST(request: NextRequest) {
  const secureCookies = useSecureCookies(request);
  const response = NextResponse.redirect(new URL("/", appOrigin(request)), { status: 303 });
  response.headers.set("Cache-Control", "no-store");
  response.headers.set("Clear-Site-Data", "\"cache\"");
  response.cookies.set(SESSION_COOKIE, "", {
    httpOnly: true,
    sameSite: "lax",
    secure: secureCookies,
    path: "/",
    maxAge: 0
  });
  return response;
}
