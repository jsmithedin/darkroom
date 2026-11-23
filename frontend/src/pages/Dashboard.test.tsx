import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { type MockApi, installMockApi, reply } from "../test/mockApi";
import { renderApp } from "../test/render";
import { Dashboard } from "./Dashboard";

// jsdom has no canvas, so stand in for the chart library.
vi.mock("../components/MonthlyChart", () => ({
  MonthlyChart: ({ label }: { label: string }) => <div role="img" aria-label={label} />,
}));

const months = () =>
  Array.from({ length: 12 }, (_, i) => ({
    month: i + 1,
    count: i === 0 ? 2 : 0,
    cumulative: 2,
  }));

const stats = (year: number) => ({
  year,
  monthly: months(),
  previous_monthly: months(),
  ytd: { this_year: 5, last_year_to_date: 3 },
  breakdowns: {
    camera: [
      { id: "c1", name: "Nikon FM2", count: 8 },
      { id: "c2", name: "Olympus XA", count: 2 },
    ],
    film: [],
    developer: [],
    format: [],
    type: [{ id: null, name: "bw", count: 10 }],
    source: [],
  },
});

let api: MockApi;
beforeEach(() => {
  api = installMockApi({
    handler: (url) => {
      if (url === "/api/stats") return reply(stats(2026));
      const year = url.match(/^\/api\/stats\?year=(\d+)$/);
      if (year) return reply(stats(Number(year[1])));
      if (url === "/api/stats/camera-idle")
        return reply([
          { camera_id: "c2", name: "Olympus XA", last_used: "2025-01-02" },
          { camera_id: "c3", name: "Holga", last_used: null },
        ]);
      if (url === "/api/stats/spend")
        return reply([
          { year: 2025, purchases_pence: 5010, bulk_pence: 300, rolls: 2, cost_per_roll_pence: 2655 },
          { year: 2026, purchases_pence: 0, bulk_pence: 100, rolls: 0, cost_per_roll_pence: null },
        ]);
      return undefined;
    },
  });
});
afterEach(() => vi.unstubAllGlobals());

it("year selector defaults to the server's current year and can change", async () => {
  const { user } = renderApp(<Dashboard />);
  const select = await screen.findByLabelText("Year");
  expect(select).toHaveValue("2026");
  expect(api.calls.find((c) => c.url.startsWith("/api/stats"))!.url).toBe("/api/stats");
  await waitFor(() => expect(within(select).getAllByRole("option")).toHaveLength(2));
  await user.selectOptions(select, "2025");
  await waitFor(() => expect(api.calls.some((c) => c.url === "/api/stats?year=2025")).toBe(true));
  expect(await screen.findByRole("img", { name: "Rolls per month in 2025" })).toBeInTheDocument();
});

it("breakdown bars scale to the largest row", async () => {
  renderApp(<Dashboard />);
  const cameras = await screen.findByRole("region", { name: "Cameras" });
  const bars = within(cameras).getAllByTestId("bar");
  expect(bars[0]).toHaveStyle({ width: "100%" });
  expect(bars[1]).toHaveStyle({ width: "25%" });
});

it("compares with the same date last year", async () => {
  renderApp(<Dashboard />);
  const ytd = await screen.findByRole("region", { name: "Year to date" });
  expect(within(ytd).getByText("5 rolls in 2026")).toBeInTheDocument();
  expect(within(ytd).getByText(/3 rolls by the same date in 2025 \(\+2\)/)).toBeInTheDocument();
});

it("lists idle cameras and spend", async () => {
  renderApp(<Dashboard />);
  const idle = await screen.findByRole("region", { name: "Cameras not used lately" });
  expect(await within(idle).findByText("Holga")).toBeInTheDocument();
  expect(within(idle).getByText("never used")).toBeInTheDocument();
  const spend = screen.getByRole("region", { name: "Spend" });
  expect(await within(spend).findByText("£26.55")).toBeInTheDocument();
  expect(within(spend).getByText("–")).toBeInTheDocument();
});
