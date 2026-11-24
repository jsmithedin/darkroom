import { screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { installMockApi, reply } from "../test/mockApi";
import { renderApp } from "../test/render";
import { Audit } from "./Audit";

const event = (over: object) => ({
  id: "e1",
  occurred_at: "2026-11-24T12:00:00Z",
  tool: "log_roll",
  entity_type: "roll",
  entity_id: "r1",
  summary: { film: { id: "f", name: "Tri-X" }, dev_date: "2026-11-20" },
  via: "oauth",
  token_id: "t1",
  client_id: "claude",
  actor: "Claude",
  ...over,
});

let items: object[];
beforeEach(() => {
  items = [
    event({}),
    event({ id: "e2", tool: "record_purchase", via: "pat", client_id: null, actor: "laptop" }),
  ];
  installMockApi({
    handler: (url) =>
      url.startsWith("/api/audit-events")
        ? reply({ items, total: items.length, limit: 50, offset: 0 })
        : undefined,
  });
});
afterEach(() => vi.unstubAllGlobals());

it("shows what changed and which connector or token did it", async () => {
  renderApp(<Audit />);
  expect(await screen.findByText("log_roll")).toBeInTheDocument();
  expect(screen.getByText("Connector: Claude")).toBeInTheDocument();
  expect(screen.getByText("Token: laptop")).toBeInTheDocument();
  expect(screen.getAllByText("Tri-X · 2026-11-20")).toHaveLength(2);
});

it("says so when there is nothing yet", async () => {
  items = [];
  renderApp(<Audit />);
  expect(await screen.findByText(/Nothing has been changed/)).toBeInTheDocument();
});
