/**
 * @jest-environment node
 */
import { NextRequest } from "next/server";
import { GET } from "../app/api/dashboard/[...path]/route";
import { POST as createSession, DELETE as clearSession } from "../app/api/dashboard/session/route";

describe("Dashboard Proxy Authentication", () => {
  const ORIGINAL_ENV = process.env;
  const originalFetch = global.fetch;

  beforeEach(() => {
    process.env = {
      ...ORIGINAL_ENV,
      NODE_ENV: "production",
      DASHBOARD_ACCESS_KEY: "super-secret-dashboard-key",
      API_READ_KEY: "backend-read-key",
      API_ADMIN_KEY: "backend-admin-key",
      INTERNAL_API_URL: "http://127.0.0.1:8000",
    };
    global.fetch = jest.fn(async () =>
      new Response(JSON.stringify({ data: [{ id: "fed-1" }] }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    ) as unknown as typeof fetch;
  });

  afterEach(() => {
    process.env = ORIGINAL_ENV;
    global.fetch = originalFetch;
    jest.restoreAllMocks();
  });

  function makeGet(path: string[], headers: Record<string, string> = {}, cookie?: string) {
    const reqHeaders = new Headers(headers);
    if (cookie) {
      reqHeaders.set("cookie", cookie);
    }
    const request = new NextRequest(`http://localhost:3000/api/dashboard/${path.join("/")}`, {
      method: "GET",
      headers: reqHeaders,
    });
    return GET(request, { params: Promise.resolve({ path }) });
  }

  it("rejects requests with missing credentials", async () => {
    const res = await makeGet(["federations"]);
    expect(res.status).toBe(401);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("rejects requests with invalid Bearer credentials", async () => {
    const res = await makeGet(["federations"], {
      Authorization: "Bearer wrong-key",
    });
    expect(res.status).toBe(401);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("rejects forged Sec-Fetch-Site: same-origin without credentials", async () => {
    const res = await makeGet(["blockchain", "transactions"], {
      "Sec-Fetch-Site": "same-origin",
    });
    expect(res.status).toBe(401);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("rejects forged Referer header without credentials", async () => {
    const res = await makeGet(["rounds", "federation", "fed-1"], {
      Referer: "http://localhost:3000/rounds",
    });
    expect(res.status).toBe(401);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("rejects unauthorized proxy path prefixes even with valid credentials", async () => {
    const res = await makeGet(["admin", "users"], {
      Authorization: "Bearer super-secret-dashboard-key",
    });
    expect(res.status).toBe(404);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("allows requests with valid Bearer credentials and injects backend key server-side", async () => {
    const res = await makeGet(["federations"], {
      Authorization: "Bearer super-secret-dashboard-key",
    });
    expect(res.status).toBe(200);
    expect(global.fetch).toHaveBeenCalledTimes(1);
    const [, fetchInit] = (global.fetch as jest.Mock).mock.calls[0];
    expect(fetchInit.headers.Authorization).toBe("Bearer backend-read-key");
  });

  it("issues HttpOnly session cookie on valid key and authorizes subsequent requests", async () => {
    const badLogin = await createSession(
      new NextRequest("http://localhost:3000/api/dashboard/session", {
        method: "POST",
        body: JSON.stringify({ key: "bad-key" }),
      }),
    );
    expect(badLogin.status).toBe(401);

    const loginRes = await createSession(
      new NextRequest("http://localhost:3000/api/dashboard/session", {
        method: "POST",
        body: JSON.stringify({ key: "super-secret-dashboard-key" }),
      }),
    );
    expect(loginRes.status).toBe(200);
    const setCookie = loginRes.headers.get("set-cookie") || "";
    expect(setCookie).toContain("trustfl_dashboard_session=");
    expect(setCookie.toLowerCase()).toContain("httponly");
    expect(setCookie.toLowerCase()).toContain("samesite=strict");

    const cookiePair = setCookie.split(";")[0];
    const authedRes = await makeGet(["federations"], {}, cookiePair);
    expect(authedRes.status).toBe(200);

    const logoutRes = await clearSession();
    expect(logoutRes.status).toBe(200);
    expect(logoutRes.headers.get("set-cookie")).toContain("Max-Age=0");
  });

  it("fails closed when DASHBOARD_ACCESS_KEY is unset", async () => {
    delete process.env.DASHBOARD_ACCESS_KEY;
    const res = await makeGet(["federations"], {
      "Sec-Fetch-Site": "same-origin",
      Referer: "http://localhost:3000/",
    });
    expect(res.status).toBe(503);
    expect(global.fetch).not.toHaveBeenCalled();
  });
});
