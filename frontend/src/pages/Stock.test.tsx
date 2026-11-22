import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { type MockApi, installMockApi, reply } from "../test/mockApi";
import { renderApp } from "../test/render";
import { Stock } from "./Stock";

const film = (id: string, name: string, type: string) => ({ id, name, type });
const fmt = (id: string, name: string) => ({ id, name });

const rows = [
  { film: film("f1", "Tri-X", "bw"), format: fmt("m35", "35mm"), rolls: 5 },
  { film: film("f2", "HP5", "bw"), format: fmt("m120", "120"), rolls: 0 },
  { film: film("f3", "Portra 400", "colour"), format: fmt("m120", "120"), rolls: 3 },
  { film: film("f4", "Velvia", "slide"), format: fmt("m35", "35mm"), rolls: 2 },
];

const spool = {
  id: "b1",
  label: "Bulk 1",
  film: film("f5", "Fomapan 100", "bw"),
  length_mm: 17000,
  left_mm: 7300,
  exposures_left: 185,
};

let api: MockApi;
beforeEach(() => {
  api = installMockApi({
    refs: {
      films: [
        { id: "f1", name: "Tri-X", archived_at: null },
        { id: "f3", name: "Portra 400", archived_at: null },
      ],
      formats: [
        { id: "m35", name: "35mm", archived_at: null },
        { id: "m120", name: "120", archived_at: null },
      ],
    },
    handler: (url, method) => {
      if (url.startsWith("/api/stock?") || url === "/api/stock") {
        const all = url.includes("include_zero=true");
        return reply(all ? rows : rows.filter((r) => r.rolls !== 0));
      }
      if (url.startsWith("/api/bulk-rolls")) return reply([spool]);
      if (url === "/api/stock-adjustments" && method === "POST") return reply({ id: "adj" }, 201);
      return undefined;
    },
  });
});
afterEach(() => vi.unstubAllGlobals());

it("groups by type and hides zero rows by default", async () => {
  renderApp(<Stock />);
  const bw = await screen.findByRole("region", { name: "Black and white" });
  expect(within(bw).getByText("Tri-X")).toBeInTheDocument();
  expect(within(screen.getByRole("region", { name: "Colour" })).getByText("Portra 400")).toBeInTheDocument();
  expect(within(screen.getByRole("region", { name: "Slide" })).getByText("Velvia")).toBeInTheDocument();
  expect(screen.queryByText("HP5")).not.toBeInTheDocument();
});

it("shows empty rows on request", async () => {
  const { user } = renderApp(<Stock />);
  await screen.findByText("Tri-X");
  await user.click(screen.getByLabelText("Show empty"));
  expect(await screen.findByText("HP5")).toBeInTheDocument();
  expect(api.calls.some((c) => c.url.includes("include_zero=true"))).toBe(true);
});

it("shows a meter for each unfinished bulk spool", async () => {
  renderApp(<Stock />);
  const bulk = await screen.findByRole("region", { name: "Bulk film" });
  expect(within(bulk).getByText("Bulk 1")).toBeInTheDocument();
  expect(within(bulk).getByText(/185 exposures left/)).toBeInTheDocument();
  expect(within(bulk).getByRole("meter")).toBeInTheDocument();
});

it("recounts a row's stock", async () => {
  const { user } = renderApp(<Stock />);
  const bw = await screen.findByRole("region", { name: "Black and white" });
  await user.click(within(bw).getAllByRole("button", { name: "Recount" })[0]);

  const form = await screen.findByRole("form", { name: "Recount stock" });
  await waitFor(() => expect(within(form).getByLabelText("Film")).toHaveValue("f1"));
  expect(within(form).getByLabelText("Format")).toHaveValue("m35");
  await user.type(within(form).getByLabelText("Rolls you actually have"), "7");
  await user.click(within(form).getByRole("button", { name: "Save recount" }));

  await waitFor(() => expect(screen.queryByRole("form", { name: "Recount stock" })).not.toBeInTheDocument());
  const post = api.calls.find((c) => c.url === "/api/stock-adjustments")!;
  expect(post.body).toMatchObject({ film_id: "f1", format_id: "m35", counted: 7 });
});

it("opens the recount form from a link on a refused write", async () => {
  renderApp(<Stock />, "/stock?recount=f3:m120");
  const form = await screen.findByRole("form", { name: "Recount stock" });
  await waitFor(() => expect(within(form).getByLabelText("Film")).toHaveValue("f3"));
  expect(within(form).getByLabelText("Format")).toHaveValue("m120");
});
