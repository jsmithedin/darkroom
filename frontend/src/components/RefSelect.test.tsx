import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { setCsrfToken, setUnauthorizedHandler } from "../api/client";
import { RefSelect } from "./RefSelect";

const items = [
  { id: "a", name: "Nikon FM2", archived_at: null },
  { id: "b", name: "Old Zenit", archived_at: "2026-01-01T00:00:00Z" },
  { id: "c", name: "Retired Leica", archived_at: "2026-02-01T00:00:00Z" },
];

beforeEach(() => {
  setCsrfToken("csrf");
  setUnauthorizedHandler(() => {});
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      expect(url).toBe("/api/cameras?include_archived=true");
      return new Response(JSON.stringify(items), {
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

function renderSelect(value: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <RefSelect kind="cameras" value={value} onChange={() => {}} label="Camera" />
    </QueryClientProvider>,
  );
}

it("hides archived items but keeps the selected archived value visible", async () => {
  renderSelect("b");
  await screen.findByRole("option", { name: "Nikon FM2" });

  expect(screen.getByRole("option", { name: "Old Zenit (archived)" })).toBeInTheDocument();
  expect(screen.queryByRole("option", { name: /Retired Leica/ })).not.toBeInTheDocument();
  expect(screen.getByLabelText("Camera")).toHaveValue("b");
});

it("hides every archived item when none is selected", async () => {
  renderSelect("");
  await screen.findByRole("option", { name: "Nikon FM2" });
  expect(screen.queryByRole("option", { name: /Zenit|Leica/ })).not.toBeInTheDocument();
});
