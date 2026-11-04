import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
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
