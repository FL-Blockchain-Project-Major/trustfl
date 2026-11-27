import { NextRequest, NextResponse } from "next/server";
import { authorizeDashboardRequest } from "../../../../libs/auth";

const API_BASE = process.env.INTERNAL_API_URL || process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
const READ_ONLY_PREFIXES = ["federations", "rounds", "updates", "clients", "artifacts", "blockchain", "health", "proofs"];

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path: routePath } = await context.params;
  const first = routePath[0];
  if (!first || !READ_ONLY_PREFIXES.includes(first)) {
    return NextResponse.json({ detail: "Path is not available through dashboard proxy" }, { status: 404 });
  }

  const auth = authorizeDashboardRequest(request);
  if (auth.authorized === false) {
    return NextResponse.json({ detail: auth.detail }, { status: auth.status });
  }

  const path = routePath.map((part) => encodeURIComponent(part)).join("/");
  const needsTrailingSlash = first === "federations" || first === "health" || request.nextUrl.pathname.endsWith("/");
  const search = request.nextUrl.search || "";
  const endpoint = `/${path}${needsTrailingSlash ? "/" : ""}${search}`;

  const headers: HeadersInit = {
    Accept: "application/json",
  };
  const traceparent = request.headers.get("traceparent");
  if (traceparent) {
    headers.traceparent = traceparent;
  }
  const key = (first === "blockchain" || first === "proofs") && process.env.API_ADMIN_KEY
    ? process.env.API_ADMIN_KEY
    : (process.env.API_READ_KEY || process.env.API_SECRET_KEY || process.env.API_ADMIN_KEY);
  if (key) {
    headers.Authorization = `Bearer ${key}`;
  }

  try {
    const response = await fetch(`${API_BASE}${endpoint}`, {
      cache: "no-store",
      headers,
    });
    const body = await response.text();
    return new NextResponse(body, {
      status: response.status,
      headers: { "content-type": response.headers.get("content-type") || "application/json" },
    });
  } catch (err) {
    console.error(`Dashboard proxy error forwarding to ${API_BASE}${endpoint}:`, err);
    return NextResponse.json({ detail: "Dashboard API is unavailable" }, { status: 503 });
  }
}
