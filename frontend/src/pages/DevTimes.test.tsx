import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { type MockApi, installMockApi, reply } from "../test/mockApi";
import { renderApp } from "../test/render";
import { DevTimes } from "./DevTimes";

const film = { id: "f1", name: "Tri-X", type: "bw" };
const developer = { id: "d1", name: "HC-110" };
const groups = [
  {
    film,
    ei: 400,
    developer,
    entries: [
      { roll_id: "r2", dev_date: "2026-03-01", minutes: 9 },
      { roll_id: "r1", dev_date: "2026-01-01", minutes: 8 },
    ],
    reference: { id: "ref1", film, ei: 400, developer, minutes: 9.5, notes: "stand" },
  },
  { film, ei: 1600, developer, entries: [], reference: null },
];

let api: MockApi;
beforeEach(() => {
  api = installMockApi({
    refs: {
      films: [{ id: "f1", name: "Tri-X", archived_at: null }],
      developers: [{ id: "d1", name: "HC-110", archived_at: null }],
    },
    handler: (url, method) => {
      if (url.startsWith("/api/dev-times")) return reply(groups);
      if (url === "/api/dev-time-refs" && method === "POST") return reply({ id: "new" }, 201);
      if (url.startsWith("/api/dev-time-refs/") && method === "PATCH") return reply({ id: "ref1" });
      if (url.startsWith("/api/dev-time-refs/") && method === "DELETE") return reply(null, 204);
      return undefined;
    },
  });
});
afterEach(() => vi.unstubAllGlobals());

it("shows each group with its reference and logged times", async () => {
  renderApp(<DevTimes />);
  const group = await screen.findByRole("region", { name: "Tri-X at EI 400 in HC-110" });
  expect(within(group).getByText("9.5 min")).toBeInTheDocument();
  expect(within(group).getAllByRole("row")).toHaveLength(3); // header + two entries
  const bare = screen.getByRole("region", { name: "Tri-X at EI 1600 in HC-110" });
  expect(within(bare).getByText("No reference time.")).toBeInTheDocument();
});

it("filters through the query string", async () => {
  const { user } = renderApp(<DevTimes />);
  await screen.findByText(/EI 400/);
  await user.type(screen.getByLabelText("EI"), "800");
  await waitFor(() => expect(api.calls.some((c) => c.url === "/api/dev-times?ei=800")).toBe(true));
});

it("adds a reference time", async () => {
  const { user } = renderApp(<DevTimes />);
  await user.click(await screen.findByRole("button", { name: "Add a reference time" }));
  const form = await screen.findByRole("form", { name: "Add reference time" });
  await waitFor(() => expect(within(form).getByRole("option", { name: "Tri-X" })).toBeInTheDocument());
  await user.selectOptions(within(form).getByLabelText("Film"), "f1");
  await user.selectOptions(within(form).getByLabelText("Developer"), "d1");
  await user.type(within(form).getByLabelText("EI"), "800");
  await user.type(within(form).getByLabelText("Minutes"), "11");
  await user.click(within(form).getByRole("button", { name: "Save reference" }));
  await waitFor(() => expect(api.calls.find((c) => c.method === "POST")).toBeTruthy());
  expect(api.calls.find((c) => c.method === "POST")!.body).toEqual({
    film_id: "f1",
    developer_id: "d1",
    ei: 800,
    minutes: 11,
    notes: null,
  });
});

it("edits and deletes a reference time", async () => {
  const { user } = renderApp(<DevTimes />);
  const group = await screen.findByRole("region", { name: "Tri-X at EI 400 in HC-110" });
  await user.click(within(group).getByRole("button", { name: "Edit" }));
  const minutes = within(group).getByLabelText("Minutes");
  await user.clear(minutes);
  await user.type(minutes, "10");
  await user.click(within(group).getByRole("button", { name: "Save" }));
  await waitFor(() => expect(api.calls.find((c) => c.method === "PATCH")).toBeTruthy());
  expect(api.calls.find((c) => c.method === "PATCH")!.body).toEqual({ minutes: 10 });

  vi.spyOn(window, "confirm").mockReturnValue(true);
  await user.click(within(group).getByRole("button", { name: "Delete" }));
  await waitFor(() => expect(api.calls.some((c) => c.method === "DELETE")).toBe(true));
});
