export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

let csrfToken: string | null = null;
let onUnauthorized: () => void = () => {
  if (window.location.pathname !== "/login") window.location.assign("/login");
};

/** Replace the 401 behaviour (tests, or a router-aware redirect). */
export function setUnauthorizedHandler(fn: () => void): void {
  onUnauthorized = fn;
}

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

const SAFE = new Set(["GET", "HEAD", "OPTIONS"]);

async function detail(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // not JSON
  }
  return res.statusText || `HTTP ${res.status}`;
}

/**
 * Fetch JSON from the API. Sends the session cookie, adds `X-CSRF-Token` on unsafe methods
 * (fetching it from /api/me if we do not have it yet) and sends 401s to the login page.
 */
export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (init.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (!SAFE.has(method)) {
    if (!csrfToken) await apiFetch("/api/me");
    if (csrfToken) headers.set("X-CSRF-Token", csrfToken);
  }

  const res = await fetch(path, { ...init, method, headers, credentials: "same-origin" });
  if (res.status === 401) {
    csrfToken = null;
    onUnauthorized();
    throw new ApiError(401, "Not signed in");
  }
  if (!res.ok) throw new ApiError(res.status, await detail(res));
  if (res.status === 204) return undefined as T;
  const data = await res.json();
  if (path === "/api/me" && typeof data?.csrf_token === "string") csrfToken = data.csrf_token;
  return data as T;
}
