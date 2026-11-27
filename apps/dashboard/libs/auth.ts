import crypto from "node:crypto";
import type { NextRequest } from "next/server";

export const SESSION_COOKIE_NAME = "trustfl_dashboard_session";
const SESSION_TTL_MS = 8 * 60 * 60 * 1000;

export function isProductionEnv(): boolean {
  return (
    process.env.NODE_ENV === "production" ||
    process.env.ENVIRONMENT?.toLowerCase() === "production"
  );
}

export function safeTokenEqual(provided: string, expected: string): boolean {
  if (!provided || !expected) {
    return false;
  }
  const providedDigest = crypto.createHash("sha256").update(provided, "utf8").digest();
  const expectedDigest = crypto.createHash("sha256").update(expected, "utf8").digest();
  return crypto.timingSafeEqual(providedDigest, expectedDigest);
}

function deriveSigningKey(secret: string): Buffer {
  return crypto.createHmac("sha256", secret).update("trustfl-dashboard-session-v1").digest();
}

export function signSessionToken(secret: string, nowMs: number = Date.now()): string {
  const expiresAt = nowMs + SESSION_TTL_MS;
  const payload = `v1.${expiresAt}`;
  const sig = crypto.createHmac("sha256", deriveSigningKey(secret)).update(payload).digest("hex");
  return `${payload}.${sig}`;
}

export function verifySessionToken(token: string, secret: string, nowMs: number = Date.now()): boolean {
  if (!token || !secret) {
    return false;
  }
  const parts = token.split(".");
  if (parts.length !== 3 || parts[0] !== "v1") {
    return false;
  }
  const expiresAt = Number(parts[1]);
  if (!Number.isFinite(expiresAt) || expiresAt <= nowMs) {
    return false;
  }
  const payload = `${parts[0]}.${parts[1]}`;
  const expectedSig = crypto
    .createHmac("sha256", deriveSigningKey(secret))
    .update(payload)
    .digest("hex");
  return safeTokenEqual(parts[2], expectedSig);
}

export type AuthCheckResult =
  | { authorized: true }
  | { authorized: false; status: 401 | 503; detail: string };

/**
 * Authenticate a dashboard proxy request using either:
 * 1. Authorization: Bearer <DASHBOARD_ACCESS_KEY | API_READ_KEY | API_ADMIN_KEY>
 * 2. HttpOnly HMAC-signed session cookie issued by /api/dashboard/session
 *
 * Client-controlled headers (Sec-Fetch-Site, Referer, Origin) are never trusted.
 */
export function authorizeDashboardRequest(request: NextRequest): AuthCheckResult {
  const dashboardKey = process.env.DASHBOARD_ACCESS_KEY?.trim() || "";
  const readKey = process.env.API_READ_KEY?.trim() || "";
  const adminKey = process.env.API_ADMIN_KEY?.trim() || "";

  if (!dashboardKey) {
    if (!isProductionEnv() && process.env.ALLOW_UNAUTHENTICATED_DASHBOARD === "true") {
      return { authorized: true };
    }
    return {
      authorized: false,
      status: 503,
      detail: "Dashboard authentication is not configured",
    };
  }

  const authHeader = request.headers.get("authorization") || request.headers.get("Authorization");
  if (authHeader) {
    const match = authHeader.match(/^Bearer\s+(.+)$/i);
    const token = match ? match[1].trim() : "";
    if (
      token &&
      (safeTokenEqual(token, dashboardKey) ||
        (readKey && safeTokenEqual(token, readKey)) ||
        (adminKey && safeTokenEqual(token, adminKey)))
    ) {
      return { authorized: true };
    }
    return {
      authorized: false,
      status: 401,
      detail: "Invalid dashboard credentials",
    };
  }

  const sessionCookie = request.cookies.get(SESSION_COOKIE_NAME)?.value || "";
  if (sessionCookie && verifySessionToken(sessionCookie, dashboardKey)) {
    return { authorized: true };
  }

  return {
    authorized: false,
    status: 401,
    detail: "Dashboard authentication required",
  };
}
