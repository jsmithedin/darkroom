import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { type MockApi, installMockApi, reply } from "../test/mockApi";
import { renderApp } from "../test/render";
import { Purchases } from "./Purchases";

const film = { id: "f1", name: "Tri-X", type: "bw" };
const spools = [
  {
    id: "b1",
    label: "Bulk 1",
    film: { id: "f5", name: "Fomapan 100", type: "bw" },
    length_mm: 17000,
    left_mm: 7300,
    exposures_left: 185,
  },
  {
    id: "b2",
    label: "Bulk 2",
    film: { id: "f1", name: "Tri-X", type: "bw" },
    length_mm: 30480,
    left_mm: 30480,
    exposures_left: 800,
  },
];

let api: MockApi;
let refuse = false;

beforeEach(() => {
  refuse = false;
  api = installMockApi({
    refs: {
      films: [{ id: "f1", name: "Tri-X", archived_at: null, type: "bw", box_iso: 400 }],
      formats: [{ id: "m35", name: "35mm", archived_at: null }],
    },
    handler: (url, method, body) => {
      if (url === "/api/bulk-rolls" && method === "POST") return reply({ ...spools[0], ...body }, 201);
      if (url.startsWith("/api/bulk-rolls")) return reply(spools);
      if (url === "/api/settings") {
        return reply({ leader_mm: 250, frame_pitch_mm: 38, timezone: "Europe/London" });
      }
      if (url.startsWith("/api/stock-movements") && method === "GET") {
        return reply({ items: [], total: 0 });
      }
      if (url === "/api/stock-movements" && method === "POST") {
        if (refuse) {
          return reply(
            {
              detail: "No Tri-X 35mm in stock. Record a purchase or a recount first.",
              code: "insufficient_stock",
              film_id: "f1",
              format_id: "m35",
              film: "Tri-X",
              format: "35mm",
              available: 0,
            },
            409,
          );
        }
        return reply({ id: "new", ...body }, 201);
      }
      return undefined;
    },
  });
  void film;
});
afterEach(() => vi.unstubAllGlobals());

const post = () => api.calls.find((c) => c.method === "POST" && c.url === "/api/stock-movements");

it("offers Bought, Bulk spool, Loaded from bulk and Given away modes", async () => {
  const { user } = renderApp(<Purchases />);
  const tabs = within(screen.getByRole("tablist"));
  expect(tabs.getByRole("tab", { name: "Bought" })).toHaveAttribute("aria-selected", "true");
  expect(tabs.getByRole("tab", { name: "Bulk spool" })).toBeInTheDocument();
  expect(tabs.getByRole("tab", { name: "Loaded from bulk" })).toBeInTheDocument();
  expect(tabs.getByRole("tab", { name: "Given away" })).toBeInTheDocument();

  expect(screen.getByRole("form", { name: "Bought film" })).toBeInTheDocument();
  await user.click(tabs.getByRole("tab", { name: "Loaded from bulk" }));
  expect(screen.getByRole("form", { name: "Loaded from bulk" })).toBeInTheDocument();
  await user.click(tabs.getByRole("tab", { name: "Given away" }));
  expect(screen.getByRole("form", { name: "Given away" })).toBeInTheDocument();
});

it("records a purchase with the cost in pence", async () => {
  const { user } = renderApp(<Purchases />);
  await waitFor(() => expect(screen.getByRole("option", { name: "Tri-X" })).toBeInTheDocument());
  await user.selectOptions(screen.getByLabelText("Film"), "Tri-X");
  await user.selectOptions(screen.getByLabelText("Format"), "35mm");
  await user.type(screen.getByLabelText("Number of rolls"), "5");
  await user.type(screen.getByLabelText("Total cost (£)"), "25.50");
  await user.click(screen.getByRole("button", { name: "Record purchase" }));

  expect(await screen.findByText("Recorded.")).toBeInTheDocument();
  expect(post()!.body).toMatchObject({
    kind: "purchase",
    film_id: "f1",
    format_id: "m35",
    rolls: 5,
    cost_pence: 2550,
    supplier: null,
  });
});

it("bulk mode shows metres and exposures left for the chosen spool", async () => {
  const { user } = renderApp(<Purchases />);
  await user.click(screen.getByRole("tab", { name: "Loaded from bulk" }));
  await waitFor(() => expect(screen.getByRole("option", { name: /Bulk 1/ })).toBeInTheDocument());
  expect(screen.queryByRole("meter")).not.toBeInTheDocument();

  await user.selectOptions(screen.getByLabelText("Bulk spool"), "b1");
  expect(screen.getByText(/7.3 m left of 17 m/)).toBeInTheDocument();
  expect(screen.getByText(/185 exposures left/)).toBeInTheDocument();

  await user.selectOptions(screen.getByLabelText("Bulk spool"), "b2");
  expect(screen.getByText(/800 exposures left/)).toBeInTheDocument();
});

it("bulk mode previews the film a load will use and records it", async () => {
  const { user } = renderApp(<Purchases />);
  await user.click(screen.getByRole("tab", { name: "Loaded from bulk" }));
  await waitFor(() => expect(screen.getByRole("option", { name: /Bulk 1/ })).toBeInTheDocument());
  await user.selectOptions(screen.getByLabelText("Bulk spool"), "b1");
  await user.type(screen.getByLabelText("Cassettes loaded"), "2");
  await waitFor(() => expect(screen.getByText(/Uses about 3.24 m/)).toBeInTheDocument()); // 2 x 1618 mm

  await user.click(screen.getByRole("button", { name: "Record load" }));
  await screen.findByText("Recorded.");
  expect(post()!.body).toMatchObject({
    kind: "bulk_load",
    bulk_roll_id: "b1",
    rolls: 2,
    exposures_per_cassette: 36,
  });
});

it("given away sends a negative number of rolls", async () => {
  const { user } = renderApp(<Purchases />);
  await user.click(screen.getByRole("tab", { name: "Given away" }));
  await waitFor(() => expect(screen.getByRole("option", { name: "Tri-X" })).toBeInTheDocument());
  await user.selectOptions(screen.getByLabelText("Film"), "Tri-X");
  await user.selectOptions(screen.getByLabelText("Format"), "35mm");
  await user.type(screen.getByLabelText("Number of rolls given away"), "2");
  await user.click(screen.getByRole("button", { name: "Record given away" }));
  await screen.findByText("Recorded.");
  expect(post()!.body).toMatchObject({ kind: "given_away", rolls: -2 });
});

it("blocked write shows the server message and a recount shortcut", async () => {
  refuse = true;
  const { user } = renderApp(<Purchases />);
  await user.click(screen.getByRole("tab", { name: "Given away" }));
  await waitFor(() => expect(screen.getByRole("option", { name: "Tri-X" })).toBeInTheDocument());
  await user.selectOptions(screen.getByLabelText("Film"), "Tri-X");
  await user.selectOptions(screen.getByLabelText("Format"), "35mm");
  await user.type(screen.getByLabelText("Number of rolls given away"), "3");
  await user.click(screen.getByRole("button", { name: "Record given away" }));

  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("No Tri-X 35mm in stock. Record a purchase or a recount first.");
  expect(within(alert).getByRole("link", { name: "Record a recount" })).toHaveAttribute(
    "href",
    "/stock?recount=f1:m35",
  );
  expect(within(alert).getByRole("link", { name: "Record a purchase" })).toHaveAttribute(
    "href",
    "/purchases?film=f1&format=m35",
  );
  expect(screen.queryByText("Recorded.")).not.toBeInTheDocument();
});

it("prefills film and format from the link on a refused write", async () => {
  renderApp(<Purchases />, "/purchases?film=f1&format=m35");
  await waitFor(() => expect(screen.getByLabelText("Film")).toHaveValue("f1"));
  expect(screen.getByLabelText("Format")).toHaveValue("m35");
});

it("records a bought bulk spool, converting metres and pounds exactly", async () => {
  api.refs.films = [{ id: "f1", name: "Fomapan 100", archived_at: null }];
  const { user } = renderApp(<Purchases />);
  await user.click(screen.getByRole("tab", { name: "Bulk spool" }));
  const form = screen.getByRole("form", { name: "Add spool" });
  // a new spool has nothing used before tracking and cannot already be finished
  expect(within(form).queryByLabelText("Used before tracking (m)")).not.toBeInTheDocument();
  expect(within(form).queryByLabelText("Finished")).not.toBeInTheDocument();

  await waitFor(() => expect(within(form).getByRole("option", { name: "Fomapan 100" })).toBeInTheDocument());
  await user.type(within(form).getByLabelText("Label"), "Bulk 2");
  await user.selectOptions(within(form).getByLabelText("Film"), "Fomapan 100");
  await user.type(within(form).getByLabelText("Length (m)"), "30.48");
  await user.type(within(form).getByLabelText("Price (£, optional)"), "30");
  await user.click(within(form).getByRole("button", { name: "Record spool" }));

  expect(await screen.findByText(/Spool recorded/)).toBeInTheDocument();
  const create = api.calls.find((c) => c.method === "POST" && c.url === "/api/bulk-rolls")!;
  expect(create.body).toMatchObject({
    label: "Bulk 2",
    film_id: "f1",
    length_mm: 30480,
    cost_pence: 3000,
    supplier: null,
    used_before_mm: 0,
    finished: false,
  });
  expect(create.body?.bought_on).toMatch(/^\d{4}-\d{2}-\d{2}$/); // defaults to today
  // the form is cleared ready for the next one
  expect(screen.getByLabelText("Label")).toHaveValue("");
});

it("an unpriced spool needs no price, but a bad price is refused", async () => {
  api.refs.films = [{ id: "f1", name: "Fomapan 100", archived_at: null }];
  const { user } = renderApp(<Purchases />);
  await user.click(screen.getByRole("tab", { name: "Bulk spool" }));
  const form = screen.getByRole("form", { name: "Add spool" });
  await waitFor(() => expect(within(form).getByRole("option", { name: "Fomapan 100" })).toBeInTheDocument());
  await user.type(within(form).getByLabelText("Label"), "Bulk 3");
  await user.selectOptions(within(form).getByLabelText("Film"), "Fomapan 100");
  await user.type(within(form).getByLabelText("Length (m)"), "17");
  expect(within(form).getByRole("button", { name: "Record spool" })).toBeEnabled();
  await user.type(within(form).getByLabelText("Price (£, optional)"), "abc");
  expect(within(form).getByRole("button", { name: "Record spool" })).toBeDisabled();
});
