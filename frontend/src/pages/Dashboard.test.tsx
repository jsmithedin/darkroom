import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { type MockApi, installMockApi, reply } from "../test/mockApi";
import { renderApp } from "../test/render";
import { Dashboard } from "./Dashboard";

// jsdom has no canvas, so stand in for the chart library.
vi.mock("../components/MonthlyChart", () => ({
  MonthlyChart: ({
    current,
    previous,
    label,
  }: {
    current: { label: string; points: { count: number }[] };
    previous: { label: string; points: { count: number }[] };
    label: string;
  }) => (
    <div
      role="img"
      aria-label={label}
      data-series={`${previous.label}:${previous.points.reduce((n, p) => n + p.count, 0)}|${current.label}:${current.points.reduce((n, p) => n + p.count, 0)}`}
    />
  ),
}));

const months = (jan: number) =>
  Array.from({ length: 12 }, (_, i) => ({
    month: i + 1,
    count: i === 0 ? jan : 0,
    cumulative: jan,
  }));

const stats = (year: number) => ({
  year,
  monthly: months(2),
  previous_monthly: months(7),
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
  await waitFor(() => expect(select).toHaveValue("2026"));
  expect(api.calls.some((c) => c.url === "/api/stats")).toBe(true);
  expect(api.calls.some((c) => c.url.startsWith("/api/stats?year="))).toBe(false);
  await waitFor(() => expect(within(select).getAllByRole("option")).toHaveLength(2));
  await user.selectOptions(select, "2025");
  await waitFor(() => expect(api.calls.some((c) => c.url === "/api/stats?year=2025")).toBe(true));
  expect(
    await screen.findByRole("img", { name: "Rolls per month in 2025, compared with 2024" }),
  ).toBeInTheDocument();
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


it("sends both years to the chart", async () => {
  renderApp(<Dashboard />);
  const chart = await screen.findByRole("img", { name: /Rolls per month in 2026/ });
  expect(chart).toHaveAttribute("data-series", "2025:7|2026:2");
});

it("keeps the year selector when the stats request fails", async () => {
  api.handler = (url) => {
    if (url === "/api/stats") return reply(stats(2026));
    if (url.startsWith("/api/stats?year=")) return reply({ detail: "nope" }, 500);
    if (url === "/api/stats/spend") return reply([{ year: 1850, purchases_pence: 0, bulk_pence: 0, rolls: 0, cost_per_roll_pence: null }, { year: 2025, purchases_pence: 0, bulk_pence: 0, rolls: 0, cost_per_roll_pence: null }]);
    if (url === "/api/stats/camera-idle") return reply([]);
    return undefined;
  };
  const { user } = renderApp(<Dashboard />);
  const select = await screen.findByLabelText("Year");
  await waitFor(() => expect(within(select).getAllByRole("option")).toHaveLength(2));
  expect(within(select).queryByRole("option", { name: "1850" })).not.toBeInTheDocument();
  await user.selectOptions(select, "2025");
  expect(await screen.findByText(/Could not load the statistics/)).toBeInTheDocument();
  expect(screen.getByLabelText("Year")).toBeInTheDocument();
});

it("says so, with a retry, when spend or cameras fail to load", async () => {
  api.handler = (url) => {
    if (url === "/api/stats") return reply(stats(2026));
    if (url === "/api/stats/spend") return reply({ detail: "down" }, 500);
    if (url === "/api/stats/camera-idle") return reply({ detail: "down" }, 500);
    return undefined;
  };
  renderApp(<Dashboard />);
  const spend = await screen.findByRole("region", { name: "Spend" });
  expect(await within(spend).findByText(/Could not load the spend figures/)).toBeInTheDocument();
  expect(within(spend).getByRole("button", { name: "Try again" })).toBeInTheDocument();
  const idle = screen.getByRole("region", { name: "Cameras not used lately" });
  expect(await within(idle).findByText(/Could not load the cameras/)).toBeInTheDocument();
});
