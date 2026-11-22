import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { setCsrfToken, setUnauthorizedHandler } from "../api/client";
import { Settings } from "./Settings";

const SECRET = "drk_abcdSECRETSECRETSECRET";

const stored = {
  id: "1",
  name: "Claude Code",
  prefix: "drk_abcd",
  scopes: ["films:read"],
  created_at: "2026-11-22T10:00:00Z",
  expires_at: null,
  last_used_at: null,
  revoked_at: null,
};

beforeEach(() => {
  setCsrfToken("csrf");
  setUnauthorizedHandler(() => {});
  let tokens: unknown[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const reply = (b: unknown, s = 200) =>
        new Response(JSON.stringify(b), { status: s, headers: { "Content-Type": "application/json" } });
      if (url === "/api/tokens" && init.method === "POST") {
        tokens = [stored];
        return reply({ ...stored, token: SECRET }, 201);
      }
      if (url === "/api/tokens") return reply(tokens);
      throw new Error(`unexpected ${url}`);
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

function renderSettings() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <Settings />
    </QueryClientProvider>,
  );
}

it("shows the token plaintext once, then hides it", async () => {
  const user = userEvent.setup();
  renderSettings();
  await screen.findByText("No tokens yet.");

  await user.type(screen.getByLabelText("Name"), "Claude Code");
  await user.click(screen.getByRole("button", { name: "Create token" }));

  expect(await screen.findByText(SECRET)).toBeInTheDocument();
  expect(screen.getByText(/will not be shown again/i)).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "I have saved it" }));
  expect(screen.queryByText(SECRET)).not.toBeInTheDocument();

  // the list only ever has the prefix
  await waitFor(() => expect(screen.getByText("Claude Code")).toBeInTheDocument());
  expect(screen.getByText("drk_abcd…")).toBeInTheDocument();
  expect(document.body.textContent).not.toContain("SECRETSECRET");
});

it("creates read-only tokens unless write is ticked", async () => {
  const user = userEvent.setup();
  renderSettings();
  await screen.findByText("No tokens yet.");
  await user.type(screen.getByLabelText("Name"), "x");
  await user.click(screen.getByRole("button", { name: "Create token" }));
  await screen.findByText(SECRET);

  const fetchFn = vi.mocked(fetch);
  const post = fetchFn.mock.calls.find(([, init]) => init?.method === "POST")!;
  expect(JSON.parse(post[1]!.body as string).scopes).toEqual(["films:read"]);
});
