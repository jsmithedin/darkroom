import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { setCsrfToken, setUnauthorizedHandler } from "../api/client";
import { RefList } from "./RefList";

type Item = Record<string, unknown> & { id: string; name: string; archived_at: string | null };

let store: Item[];

const reply = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

beforeEach(() => {
  setCsrfToken("csrf");
  setUnauthorizedHandler(() => {});
  store = [{ id: "1", name: "Nikon FM2", archived_at: null, fixed_lens: false, notes: null }];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = init.method ?? "GET";
      const [path, query] = url.split("?");
      if (path === "/api/cameras" && method === "GET") {
        const all = query?.includes("include_archived=true");
        return reply(store.filter((i) => all || !i.archived_at));
      }
      if (path === "/api/cameras" && method === "POST") {
        const body = JSON.parse(init.body as string);
        if (store.some((i) => i.name.toLowerCase() === body.name.toLowerCase())) {
          return reply({ detail: `A camera named '${body.name}' already exists.` }, 409);
        }
        const item = { id: String(store.length + 1), archived_at: null, ...body };
        store.push(item);
        return reply(item, 201);
      }
      const archive = path.match(/^\/api\/cameras\/(\w+)\/(archive|unarchive)$/);
      if (archive && method === "POST") {
        const item = store.find((i) => i.id === archive[1])!;
        item.archived_at = archive[2] === "archive" ? "2026-11-22T00:00:00Z" : null;
        return reply(item);
      }
      throw new Error(`unexpected ${method} ${url}`);
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

function renderList() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <RefList kind="cameras" singular="camera" />
    </QueryClientProvider>,
  );
}

it("adds a camera with its extra fields", async () => {
  const user = userEvent.setup();
  renderList();
  await screen.findByText("Nikon FM2");

  await user.click(screen.getByRole("button", { name: "Add camera" }));
  await user.type(screen.getByLabelText("Name"), "Olympus XA");
  await user.click(screen.getByLabelText("Fixed lens"));
  await user.click(screen.getByRole("button", { name: "Add camera" }));

  expect(await screen.findByText("Olympus XA")).toBeInTheDocument();
  expect(store[1]).toMatchObject({ name: "Olympus XA", fixed_lens: true });
  expect(screen.getByText("Fixed lens")).toBeInTheDocument();
});

it("shows the server's message for a duplicate name", async () => {
  const user = userEvent.setup();
  renderList();
  await screen.findByText("Nikon FM2");

  await user.click(screen.getByRole("button", { name: "Add camera" }));
  await user.type(screen.getByLabelText("Name"), "nikon fm2");
  await user.click(screen.getByRole("button", { name: "Add camera" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("already exists");
  expect(store).toHaveLength(1);
});

it("archives an item, hides it, and shows it again under 'Show archived'", async () => {
  const user = userEvent.setup();
  renderList();
  await screen.findByText("Nikon FM2");

  await user.click(screen.getByRole("button", { name: "Archive" }));
  await waitFor(() => expect(screen.queryByText("Nikon FM2")).not.toBeInTheDocument());

  await user.click(screen.getByLabelText("Show archived"));
  expect(await screen.findByText("Nikon FM2")).toBeInTheDocument();
  expect(screen.getByText("archived")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Unarchive" }));
  await waitFor(() => expect(screen.queryByText("archived")).not.toBeInTheDocument());
});
