import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { type MockApi, installMockApi, reply } from "../test/mockApi";
import { renderApp } from "../test/render";
import { SettingsBulk } from "./SettingsBulk";

const spool = {
  id: "b1",
  label: "Bulk 1",
  film: { id: "f1", name: "Fomapan 100", type: "bw" },
  length_mm: 17000,
  cost_pence: null,
  supplier: null,
  bought_on: null,
  used_before_mm: 9700,
  finished: false,
  notes: null,
  cassettes_loaded: 0,
  used_mm: 9700,
  left_mm: 7300,
  exposures_left: 185,
  cost_per_36_pence: null,
};

let api: MockApi;
let deleteRefusal = false;

beforeEach(() => {
  deleteRefusal = false;
  api = installMockApi({
    refs: { films: [{ id: "f1", name: "Fomapan 100", archived_at: null }] },
    handler: (url, method, body) => {
      if (url === "/api/settings" && method === "GET") {
        return reply({ leader_mm: 250, frame_pitch_mm: 38, timezone: "Europe/London" });
      }
      if (url === "/api/settings" && method === "PATCH") return reply(body);
      if (url.startsWith("/api/bulk-rolls") && method === "GET") return reply([spool]);
      if (url === "/api/bulk-rolls/b1" && method === "PATCH") return reply({ ...spool, ...body });
      if (url === "/api/bulk-rolls/b1" && method === "DELETE") {
        return deleteRefusal
          ? reply({ detail: "'Bulk 1' has 2 cassette load(s) recorded against it." }, 409)
          : reply(null, 204);
      }
      return undefined;
    },
  });
});
afterEach(() => vi.unstubAllGlobals());

it("shows the current maths and saves changes", async () => {
  const { user } = renderApp(<SettingsBulk />);
  const leader = await screen.findByLabelText("Leader per cassette (mm)");
  await waitFor(() => expect(leader).toHaveValue("250"));
  expect(screen.getByLabelText("Frame pitch (mm per exposure)")).toHaveValue("38");

  await user.clear(leader);
  await user.type(leader, "300");
  await user.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByText("Saved.")).toBeInTheDocument();
  const patch = api.calls.find((c) => c.method === "PATCH" && c.url === "/api/settings")!;
  expect(patch.body).toEqual({ leader_mm: 300, frame_pitch_mm: 38, timezone: "Europe/London" });
});

it("will not save a non-positive leader", async () => {
  const { user } = renderApp(<SettingsBulk />);
  const leader = await screen.findByLabelText("Leader per cassette (mm)");
  await waitFor(() => expect(leader).toHaveValue("250"));
  await user.clear(leader);
  await user.type(leader, "0");
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
});

it("lists spools with their meter and unpriced status", async () => {
  renderApp(<SettingsBulk />);
  const list = await screen.findByRole("region", { name: "Bulk spools" });
  expect(await within(list).findByText("Bulk 1")).toBeInTheDocument();
  expect(within(list).getByText(/unpriced/)).toBeInTheDocument();
  expect(within(list).getByText(/185 exposures left/)).toBeInTheDocument();
});

it("points to Purchases for buying a new spool, and has no add button", async () => {
  renderApp(<SettingsBulk />);
  await screen.findByText("Bulk 1");
  expect(screen.queryByRole("button", { name: "Add spool" })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Purchases" })).toHaveAttribute("href", "/purchases");
});

it("edits a spool, keeping the used-before-tracking and finished fields", async () => {
  const { user } = renderApp(<SettingsBulk />);
  await screen.findByText("Bulk 1");
  await user.click(screen.getByRole("button", { name: "Edit" }));
  const form = screen.getByRole("form", { name: "Edit spool" });
  expect(within(form).getByLabelText("Used before tracking (m)")).toHaveValue("9.7");
  expect(within(form).getByLabelText("Finished")).not.toBeChecked();
  await user.click(within(form).getByLabelText("Finished"));
  await user.click(within(form).getByRole("button", { name: "Save spool" }));
  await waitFor(() => expect(screen.queryByRole("form", { name: "Edit spool" })).not.toBeInTheDocument());
  const patch = api.calls.find((c) => c.method === "PATCH" && c.url === "/api/bulk-rolls/b1")!;
  expect(patch.body).toMatchObject({ finished: true, used_before_mm: 9700, length_mm: 17000 });
});

it("deleting a spool with loads shows the server's refusal", async () => {
  deleteRefusal = true;
  const { user } = renderApp(<SettingsBulk />);
  await screen.findByText("Bulk 1");
  vi.spyOn(window, "confirm").mockReturnValue(true);
  await user.click(screen.getByRole("button", { name: "Delete" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("cassette load(s) recorded");
});
