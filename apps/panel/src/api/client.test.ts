import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { setReauthPrompt } from "@/lib/reauth";
import { api, normalizeError, setUnauthorizedHandler } from "./client";

function setCookie(value: string) {
  document.cookie = value;
}

function clearCookies() {
  for (const cookie of document.cookie.split(";")) {
    const name = cookie.split("=")[0]?.trim();
    if (name)
      document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/`;
  }
}

describe("CSRF", () => {
  beforeEach(() => {
    setCookie("autobot_panel_csrftoken=the-token");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request) => {
        const request = input instanceof Request ? input : new Request(input);
        return new Response(
          JSON.stringify({ username: request.headers.get("X-CSRFToken") }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          },
        );
      }),
    );
  });

  afterEach(() => {
    clearCookies();
    vi.unstubAllGlobals();
  });

  test("sets X-CSRFToken on an unsafe method", async () => {
    const { data } = await api.POST("/auth/logout");
    expect(data).toEqual({ username: "the-token" });
  });

  test("does not set X-CSRFToken on a safe method", async () => {
    const { data } = await api.GET("/auth/me");
    expect(data).toEqual({ username: null });
  });
});

describe("CSRF 403", () => {
  afterEach(() => {
    clearCookies();
    vi.unstubAllGlobals();
  });

  test("asks for a fresh token and resends once", async () => {
    setCookie("autobot_panel_csrftoken=stale");
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request) => {
        const request = input instanceof Request ? input : new Request(input);
        calls.push(`${request.method} ${new URL(request.url).pathname}`);
        if (request.url.endsWith("/auth/csrf")) {
          setCookie("autobot_panel_csrftoken=fresh");
          return new Response("{}", { status: 200 });
        }
        const token = request.headers.get("X-CSRFToken");
        return token === "fresh"
          ? new Response(JSON.stringify({ ok: true }), { status: 200 })
          : new Response(JSON.stringify({ detail: "CSRF check Failed" }), {
              status: 403,
            });
      }),
    );
    const { data } = await api.POST("/auth/logout");
    expect(data).toEqual({ ok: true });
    expect(calls).toEqual([
      "POST /api/panel/auth/logout",
      "GET /api/panel/auth/csrf",
      "POST /api/panel/auth/logout",
    ]);
  });

  test("does not retry a 403 that is not about CSRF", async () => {
    setCookie("autobot_panel_csrftoken=t");
    const fetchMock = vi.fn(
      async () =>
        new Response(JSON.stringify({ detail: "no" }), { status: 403 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { response } = await api.POST("/auth/logout");
    expect(response.status).toBe(403);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("401 outside auth/me and auth/login", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify({ detail: "no" }), { status: 401 }),
      ),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    setUnauthorizedHandler(() => {});
  });

  test("triggers the unauthorized handler", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    await api.GET("/data/tables");
    expect(handler).toHaveBeenCalledOnce();
  });

  test("auth/me does not trigger the unauthorized handler", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    await api.GET("/auth/me");
    expect(handler).not.toHaveBeenCalled();
  });
});

describe("normalizeError", () => {
  test("passes through the backend's {code, message, details} shape", () => {
    expect(
      normalizeError(
        { code: "not_found", message: "No encontrado.", details: [] },
        404,
      ),
    ).toEqual({
      code: "not_found",
      message: "No encontrado.",
      details: [],
      status: 404,
    });
  });

  test("maps django-ninja's {detail} shape to unauthorized", () => {
    expect(
      normalizeError(
        { detail: "Authentication credentials were not provided." },
        401,
      ),
    ).toEqual({
      code: "unauthorized",
      message: "Authentication credentials were not provided.",
      details: [],
      status: 401,
    });
  });

  test("falls back to unknown for anything else", () => {
    expect(normalizeError(undefined, 500).code).toBe("unknown");
  });
});

describe("reauth_required", () => {
  afterEach(() => {
    setReauthPrompt(null);
    vi.unstubAllGlobals();
  });

  function stubReauthServer() {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request) => {
        const request = input instanceof Request ? input : new Request(input);
        calls.push(request.url);
        if (calls.length === 1)
          return new Response(
            JSON.stringify({
              code: "reauth_required",
              message: "Confirma",
              details: [],
            }),
            { status: 403, headers: { "Content-Type": "application/json" } },
          );
        return new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );
    return calls;
  }

  test("prompts for a code, then resends the action once", async () => {
    const calls = stubReauthServer();
    setReauthPrompt((settle) => settle(true));
    const { data } = await api.POST("/auth/logout");
    expect(data).toEqual({ ok: true });
    expect(calls).toHaveLength(2);
  });

  test("returns the 403 when the person cancels", async () => {
    const calls = stubReauthServer();
    setReauthPrompt((settle) => settle(false));
    const { error, response } = await api.POST("/auth/logout");
    expect(response.status).toBe(403);
    expect(error).toMatchObject({ code: "reauth_required" });
    expect(calls).toHaveLength(1);
  });
});

describe("resent requests still pass through the other middlewares", () => {
  afterEach(() => {
    clearCookies();
    setReauthPrompt(null);
    setUnauthorizedHandler(() => {});
    vi.unstubAllGlobals();
  });

  function csrfFailure() {
    return new Response(JSON.stringify({ detail: "CSRF check Failed" }), {
      status: 403,
    });
  }

  test("a 401 on the CSRF resend triggers the unauthorized handler", async () => {
    setCookie("autobot_panel_csrftoken=stale");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request) => {
        const request = input instanceof Request ? input : new Request(input);
        if (request.url.endsWith("/auth/csrf")) {
          setCookie("autobot_panel_csrftoken=fresh");
          return new Response("{}", { status: 200 });
        }
        return request.headers.get("X-CSRFToken") === "fresh"
          ? new Response(JSON.stringify({ detail: "no" }), { status: 401 })
          : csrfFailure();
      }),
    );
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    await api.POST("/data/query");
    expect(handler).toHaveBeenCalledOnce();
  });

  test("a reauth_required on the CSRF resend prompts and resends with the fresh token", async () => {
    setCookie("autobot_panel_csrftoken=stale");
    const sent: (string | null)[] = [];
    let reauthenticated = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request) => {
        const request = input instanceof Request ? input : new Request(input);
        if (request.url.endsWith("/auth/csrf")) {
          setCookie("autobot_panel_csrftoken=fresh");
          return new Response("{}", { status: 200 });
        }
        const token = request.headers.get("X-CSRFToken");
        sent.push(token);
        if (token !== "fresh") return csrfFailure();
        return reauthenticated
          ? new Response(JSON.stringify({ ok: true }), { status: 200 })
          : new Response(
              JSON.stringify({
                code: "reauth_required",
                message: "Confirma",
                details: [],
              }),
              { status: 403 },
            );
      }),
    );
    setReauthPrompt((settle) => {
      reauthenticated = true;
      settle(true);
    });
    const { data } = await api.POST("/auth/logout");
    expect(data).toEqual({ ok: true });
    expect(sent).toEqual(["stale", "fresh", "fresh"]);
  });
});
