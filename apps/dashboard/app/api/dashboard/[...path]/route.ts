import { NextRequest, NextResponse } from "next/server";

const API_BASE = process.env.INTERNAL_API_URL || process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export async function GET(
  _request: NextRequest,
  context: { params: { path: string[] } },
) {
  const endpoint = `/${context.params.path.map((part) => encodeURIComponent(part)).join("/")}`;
  const headers: HeadersInit = {};
  const key = process.env.API_READ_KEY || process.env.API_SECRET_KEY;
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
  } catch {
    return NextResponse.json({ detail: "Dashboard API is unavailable" }, { status: 503 });
  }
}
