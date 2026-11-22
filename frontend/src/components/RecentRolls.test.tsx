import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { type MockApi, installMockApi } from "../test/mockApi";
import { RecentRolls } from "./RecentRolls";

const roll = {
  id: "r1",
  dev_date: "2026-11-01",
  camera: { id: "cam1", name: "Nikon FM2" },
  lens: null,
  format: { id: "f35", name: "35mm" },
  film: { id: "film1", name: "Tri-X", type: "bw", box_iso: 400 },
  ei: 800,
  developer: { id: "dev1", name: "HC-110" },
  dev_time_min: 9.5,
  filter: null,
  subject: "Harbour",
  notes: null,
  source: "factory",
  counts_against_stock: true,
  stops_vs_box: "+1",
};

let api: MockApi;
beforeEach(() => {
  api = installMockApi({ rolls: [roll] });
});
afterEach(() => vi.unstubAllGlobals());

function renderRecent() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <RecentRolls />
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

it("lists recent rolls with their derived stops", async () => {
  renderRecent();
  expect(await screen.findByText("Tri-X")).toBeInTheDocument();
  expect(screen.getByText(/EI 800 \(\+1 stops\)/)).toBeInTheDocument();
  expect(screen.getByText("Harbour")).toBeInTheDocument();
});

it("deleting asks for confirmation first", async () => {
  const user = renderRecent();
  await screen.findByText("Tri-X");
  await user.click(screen.getByRole("button", { name: "Edit" }));

  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  await user.click(screen.getByRole("button", { name: "Delete" }));
  expect(confirm).toHaveBeenCalledOnce();
  expect(api.calls.some((c) => c.method === "DELETE")).toBe(false);

  confirm.mockReturnValue(true);
  await user.click(screen.getByRole("button", { name: "Delete" }));
  await waitFor(() => expect(api.calls.some((c) => c.method === "DELETE")).toBe(true));
  await waitFor(() => expect(screen.queryByText("Tri-X")).not.toBeInTheDocument());
  confirm.mockRestore();
});
