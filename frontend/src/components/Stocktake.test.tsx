import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { type MockApi, installMockApi, reply } from "../test/mockApi";
import { renderApp } from "../test/render";
import { Stocktake } from "./Stocktake";

const film = (id: string, name: string) => ({ id, name, type: "bw" });
const fmt = (id: string, name: string) => ({ id, name });

const rows = [
  { film: film("f1", "Tri-X"), format: fmt("m35", "35mm"), rolls: 5 },
  { film: film("f2", "HP5"), format: fmt("m120", "120"), rolls: 0 },
  { film: film("f3", "Portra"), format: fmt("m120", "120"), rolls: 3 },
];

let api: MockApi;
let respond: () => Response | undefined;
beforeEach(() => {
  respond = () => reply({ replayed: false, adjustments: [] }, 201);
  api = installMockApi({
    refs: {
      films: [
        { id: "f1", name: "Tri-X", archived_at: null },
        { id: "f4", name: "Ektar", archived_at: null },
      ],
      formats: [
        { id: "m35", name: "35mm", archived_at: null },
        { id: "m120", name: "120", archived_at: null },
      ],
    },
    handler: (url, method) => {
      if (url === "/api/stocktakes" && method === "POST") return respond();
      if (url.startsWith("/api/stock")) return reply(rows);
      return undefined;
    },
  });
});
afterEach(() => vi.unstubAllGlobals());

type Sent = { batch_id: string; counts: { film_id: string; counted: number; expected: number }[] };
const sent = (i: number) => posts()[i].body as unknown as Sent;
const posts = () => api.calls.filter((c) => c.url === "/api/stocktakes");

it("reviews only differences, leaves blanks alone, and sends expected balances", async () => {
  const onDone = vi.fn();
  const { user } = renderApp(<Stocktake onDone={onDone} />);
  await user.type(await screen.findByLabelText("Counted Tri-X 35mm"), "4");
  await user.type(screen.getByLabelText("Counted HP5 120"), "0"); // zero balance, none found
  await user.type(screen.getByLabelText("Counted Portra 120"), "3"); // matches
  await user.click(screen.getByRole("button", { name: "Review differences" }));

  const review = await screen.findByRole("region", { name: "Review stocktake" });
  expect(within(review).getByText(/Tri-X \(35mm\)/)).toBeInTheDocument();
  expect(within(review).queryByText(/HP5/)).toBeNull();
  expect(within(review).getByText("-1")).toBeInTheDocument();
  expect(within(review).getByText("2 counted rows matched.")).toBeInTheDocument();
  expect(posts()).toHaveLength(0);

  await user.click(within(review).getByRole("button", { name: "Apply 1 change" }));
  await waitFor(() => expect(onDone).toHaveBeenCalled());
  const body = sent(0);
  expect(body.counts).toHaveLength(3);
  expect(body.counts[0]).toMatchObject({ film_id: "f2", counted: 0, expected: 0 });
  expect(body.batch_id).toBeTruthy();
});

it("cancelling the review saves nothing", async () => {
  const onDone = vi.fn();
  const { user } = renderApp(<Stocktake onDone={onDone} />);
  await user.type(await screen.findByLabelText("Counted Tri-X 35mm"), "1");
  await user.click(screen.getByRole("button", { name: "Review differences" }));
  await user.click(await screen.findByRole("button", { name: "Cancel" }));
  expect(onDone).toHaveBeenCalled();
  expect(posts()).toHaveLength(0);
});

it("rejects non-numbers and needs at least one count", async () => {
  const { user } = renderApp(<Stocktake onDone={() => {}} />);
  const review = await screen.findByRole("button", { name: "Review differences" });
  expect(review).toBeDisabled();
  await user.type(await screen.findByLabelText("Counted Tri-X 35mm"), "x");
  expect(screen.getByText("Counts must be whole numbers, 0 or more.")).toBeInTheDocument();
  expect(review).toBeDisabled();
});

it("counts a film that has no stock row", async () => {
  const { user } = renderApp(<Stocktake onDone={() => {}} />);
  await screen.findByLabelText("Counted Tri-X 35mm");
  await user.selectOptions(screen.getByLabelText("Another film"), "f4");
  await user.selectOptions(screen.getByLabelText("Format"), "m120");
  await user.click(screen.getByRole("button", { name: "Add row" }));
  await user.type(screen.getByLabelText("Counted Ektar 120"), "2");
  await user.click(screen.getByRole("button", { name: "Review differences" }));
  expect(await screen.findByText(/Ektar \(120\)/)).toBeInTheDocument();
  expect(screen.getByText("+2")).toBeInTheDocument();
});

it("flags a row whose stock changed and applies nothing until confirmed again", async () => {
  respond = () =>
    reply(
      {
        detail: "Stock changed",
        code: "stock_changed",
        rows: [
          { film_id: "f1", format_id: "m35", film: "Tri-X", format: "35mm", expected: 5, current: 6 },
        ],
      },
      409,
    );
  const { user } = renderApp(<Stocktake onDone={() => {}} />);
  await user.type(await screen.findByLabelText("Counted Tri-X 35mm"), "4");
  await user.click(screen.getByRole("button", { name: "Review differences" }));
  await user.click(await screen.findByRole("button", { name: "Apply 1 change" }));

  expect(await screen.findByText(/Stock changed since you counted/)).toBeInTheDocument();
  expect(screen.getByText(/changed from 5 to 6/)).toBeInTheDocument();
  const review = screen.getByRole("region", { name: "Review stocktake" });
  expect(within(review).getByText("-2")).toBeInTheDocument(); // 4 counted vs the new 6

  respond = () => reply({ replayed: false, adjustments: [] }, 201);
  await user.click(screen.getByRole("button", { name: "Apply 1 change" }));
  await waitFor(() => expect(posts()).toHaveLength(2));
  expect(sent(1).counts[0].expected).toBe(6);
});
