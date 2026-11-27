import { NextRequest, NextResponse } from "next/server";
import {
  SESSION_COOKIE_NAME,
  isProductionEnv,
  safeTokenEqual,
  signSessionToken,
} from "../../../../libs/auth";

export async function POST(request: NextRequest) {
  const dashboardKey = process.env.DASHBOARD_ACCESS_KEY?.trim() || "";
  if (!dashboardKey) {
    return NextResponse.json(
      { detail: "Dashboard authentication is not configured" },
      { status: 503 },
    );
  }

  let body: { key?: unknown } = {};
  try {
    body = (await request.json()) as { key?: unknown };
  } catch {
    return NextResponse.json({ detail: "Invalid JSON body" }, { status: 400 });
  }

  const providedKey = typeof body.key === "string" ? body.key.trim() : "";
  if (!providedKey || !safeTokenEqual(providedKey, dashboardKey)) {
    return NextResponse.json({ detail: "Invalid dashboard access key" }, { status: 401 });
  }

  const token = signSessionToken(dashboardKey);
  const response = NextResponse.json({ authenticated: true }, { status: 200 });
  response.cookies.set({
    name: SESSION_COOKIE_NAME,
    value: token,
    httpOnly: true,
    sameSite: "strict",
    secure: isProductionEnv() && request.nextUrl.protocol === "https:",
    path: "/",
    maxAge: 8 * 60 * 60,
  });
  return response;
}

export async function DELETE() {
  const response = NextResponse.json({ authenticated: false }, { status: 200 });
  response.cookies.set({
    name: SESSION_COOKIE_NAME,
    value: "",
    httpOnly: true,
    sameSite: "strict",
    path: "/",
    maxAge: 0,
  });
  return response;
}
