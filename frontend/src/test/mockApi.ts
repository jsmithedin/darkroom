import { vi } from "vitest";
import { setCsrfToken, setUnauthorizedHandler } from "../api/client";

type Json = Record<string, unknown>;

export interface MockApi {
  refs: Record<string, Json[]>;
  rolls: Json[];
  /** camera id -> its most recent roll (what /last-roll returns) */
  lastRolls: Record<string, Json>;
  calls: { method: string; url: string; body?: Json }[];
}

export const reply = (body: unknown, status = 200) =>
  new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

/** A small in-memory stand-in for the API, installed as the global fetch. */
export function installMockApi(initial: Partial<MockApi> = {}): MockApi {
  setCsrfToken("csrf");
  setUnauthorizedHandler(() => {});
  const api: MockApi = { refs: {}, rolls: [], lastRolls: {}, calls: [], ...initial };

  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = init.method ?? "GET";
      const body = init.body ? (JSON.parse(init.body as string) as Json) : undefined;
      api.calls.push({ method, url, body });
      const [path] = url.split("?");

      const list = path.match(/^\/api\/(cameras|lenses|formats|films|developers|filters)$/);
      if (list && method === "GET") return reply(api.refs[list[1]] ?? []);

      const last = path.match(/^\/api\/cameras\/([^/]+)\/last-roll$/);
      if (last) {
        const roll = api.lastRolls[last[1]];
        return roll ? reply(roll) : reply({ detail: "No rolls logged for this camera yet." }, 404);
      }

      if (path === "/api/rolls" && method === "GET") {
        return reply({ items: api.rolls, total: api.rolls.length, limit: 20, offset: 0 });
      }
      if (path === "/api/rolls" && method === "POST") {
        const created = { id: `r${api.rolls.length + 1}`, ...body };
        api.rolls.unshift(created);
        return reply(created, 201);
      }
      const one = path.match(/^\/api\/rolls\/([^/]+)$/);
      if (one && method === "DELETE") {
        api.rolls = api.rolls.filter((r) => r.id !== one[1]);
        return reply(null, 204);
      }
      throw new Error(`unexpected ${method} ${url}`);
    }),
  );
  return api;
}
