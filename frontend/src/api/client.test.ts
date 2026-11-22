import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiFetch, setCsrfToken, setUnauthorizedHandler } from "./client";

type Handler = (url: string, init: RequestInit) => Response;

function mockFetch(handler: Handler) {
  const fn = vi.fn(async (url: string, init: RequestInit = {}) => handler(url, init));
  vi.stubGlobal("fetch", fn);
  return fn;
}

const headersOf = (call: unknown[] | undefined) =>
  (call?.[1] as RequestInit).headers as Headers;

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

beforeEach(() => {
  setCsrfToken(null);
  setUnauthorizedHandler(() => {});
});
afterEach(() => vi.unstubAllGlobals());

describe("apiFetch", () => {
  it("adds X-CSRF-Token on POST, fetching it from /api/me first", async () => {
    const fetchFn = mockFetch((url) =>
      url === "/api/me" ? json({ email: "a", name: "A", csrf_token: "tok123" }) : json({ ok: true }),
    );
    await apiFetch("/api/things", { method: "POST", body: JSON.stringify({ a: 1 }) });

    const post = fetchFn.mock.calls.find(([url]) => url === "/api/things");
    const headers = headersOf(post);
    expect(headers.get("X-CSRF-Token")).toBe("tok123");
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("does not send a CSRF token on GET", async () => {
    const fetchFn = mockFetch(() => json({ ok: true }));
    await apiFetch("/api/things");
    expect(fetchFn).toHaveBeenCalledTimes(1);
    expect(headersOf(fetchFn.mock.calls[0]).has("X-CSRF-Token")).toBe(false);
  });

  it("reuses the cached token for later writes", async () => {
    setCsrfToken("cached");
    const fetchFn = mockFetch(() => new Response(null, { status: 204 }));
    await apiFetch("/api/things/1", { method: "DELETE" });
    expect(fetchFn).toHaveBeenCalledTimes(1);
    expect(headersOf(fetchFn.mock.calls[0]).get("X-CSRF-Token")).toBe("cached");
  });

  it("redirects to login on 401", async () => {
    const onUnauthorized = vi.fn();
    setUnauthorizedHandler(onUnauthorized);
    mockFetch(() => json({ detail: "Not authenticated" }, 401));
    await expect(apiFetch("/api/me")).rejects.toBeInstanceOf(ApiError);
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });

  it("surfaces the server's error detail", async () => {
    mockFetch(() => json({ detail: "Nope" }, 409));
    await expect(apiFetch("/api/things")).rejects.toMatchObject({ status: 409, message: "Nope" });
  });
});
