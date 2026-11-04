import createClient, { type Middleware } from "openapi-fetch";
import type { paths } from "./schema";

export interface ApiError {
  code: string;
  message: string;
  details: string[];
  status: number;
}

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
// `auth/me` is how the app checks whether a session exists, and `auth/login` is how
// it fails to create one: a 401 from either is a normal result, not a dropped session.
const PUBLIC_PATHS = new Set(["/auth/me", "/auth/login"]);

function readCookie(name: string): string | null {
  const match = document.cookie.match(`(?:^|; )${name}=([^;]*)`);
  const value = match?.[1];
  return value ? decodeURIComponent(value) : null;
}

const csrfMiddleware: Middleware = {
  onRequest({ request }) {
    if (!UNSAFE_METHODS.has(request.method)) return undefined;
    const token = readCookie("autobot_panel_csrftoken");
    if (token) request.headers.set("X-CSRFToken", token);
    return request;
  },
};

// Wired from outside (main.tsx) once the router and the query client exist, so this
// module never has to import them and risk a cycle with the routes that use `api`.
let onUnauthorized: () => void = () => {};

export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler;
}

const unauthorizedMiddleware: Middleware = {
  onResponse({ schemaPath, response }) {
    if (response.status === 401 && !PUBLIC_PATHS.has(schemaPath)) {
      onUnauthorized();
    }
    return undefined;
  },
};

// Always same-origin (ADR-008: the panel is served by Caddy at the same origin as
// the API). An absolute URL, rather than a bare "/api/panel", is also what Node's
// `Request`/`URL` (unlike a browser's) need to resolve a path at all.
export const api = createClient<paths>({
  baseUrl: `${window.location.origin}/api/panel`,
  // A lazy indirection, not `fetch` itself: openapi-fetch binds whatever it is given
  // once, at client creation, so tests that stub `globalThis.fetch` after this
  // module loads need the lookup to happen per request instead.
  fetch: (...args) => globalThis.fetch(...args),
});
api.use(csrfMiddleware, unauthorizedMiddleware);

function isApiErrorBody(
  value: unknown,
): value is { code: string; message: string; details?: string[] } {
  return (
    typeof value === "object" &&
    value !== null &&
    "code" in value &&
    "message" in value &&
    typeof (value as { code: unknown }).code === "string" &&
    typeof (value as { message: unknown }).message === "string"
  );
}

function isNinjaErrorBody(value: unknown): value is { detail: string } {
  return (
    typeof value === "object" &&
    value !== null &&
    "detail" in value &&
    typeof (value as { detail: unknown }).detail === "string"
  );
}

export function normalizeError(error: unknown, status: number): ApiError {
  if (isApiErrorBody(error)) {
    return {
      code: error.code,
      message: error.message,
      details: error.details ?? [],
      status,
    };
  }
  if (isNinjaErrorBody(error)) {
    return { code: "unauthorized", message: error.detail, details: [], status };
  }
  return { code: "unknown", message: "Error inesperado.", details: [], status };
}

/** Throws `ApiError` on failure, so callers (react-query) only ever see `T`. */
export async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await call;
  if (error !== undefined) throw normalizeError(error, response.status);
  if (data === undefined) throw normalizeError(undefined, response.status);
  return data;
}
